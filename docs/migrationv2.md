# Jarvis Desktop – Production System Design (Local‑First)

This document explains **step by step** how the production Electron app, Python server, Redis, and AI models work together.

It is written so that:

* New contributors understand the full picture
* Future agents can reason correctly
* Architecture decisions are explicit and intentional

---

## 1. Core Philosophy

Jarvis is a **local‑first desktop AI system**.

Key principles:

* Fast response (local execution)
* Works offline (after models installed)
* Secure (no arbitrary cloud dependency)
* Update‑safe (models & memory persist)

Electron is the **orchestrator**.
Python FastAPI is the **brain**.
Redis is the **fast memory bus**.

---

## 2. High‑Level Architecture

```
User
  ↓
Electron App (UI + Orchestrator)
  ↓ WebSocket / HTTP
Local FastAPI Server (jarvis‑core)
  ↓
Redis (local standalone process)
  ↓
Models (stored in AppData)
```

Electron controls **lifecycle**.
Server controls **logic**.
Redis controls **speed & state**.

---

## 3. What Is Bundled vs What Persists

### 3.1 Read‑Only (Bundled with app)

These are versioned and replaced on update:

```
Jarvis.exe
resources/
└── app/
    ├── python/              ← embedded Python runtime
    ├── jarvis‑core/         ← FastAPI server code
    ├── redis‑server.exe
    ├── tools/
    └── version.json
```

* No user data here
* Treated as **immutable**

---

### 3.2 Writable & Persistent (User Data)

Lives outside the app bundle:

**Windows**

```
C:\Users\<user>\AppData\Roaming\SparkAI\
```

Structure:

```
SparkAI/
├── models/           ← 5–6GB AI models
├── redis/
│   └── dump.rdb
├── memory/
├── logs/
└── config.json
```

✔ Survives updates
✔ Writable
✔ User‑owned

---

## 4. First Install Flow

1. User installs Jarvis (Electron installer)
2. User launches Jarvis
3. Electron determines OS paths
4. Electron creates AppData folders
5. Electron starts Redis
6. Electron starts Python server
7. UI becomes active

No terminal. No manual steps.

---

## 5. Redis Lifecycle (Standalone EXE)

### Why Redis?

* Ultra‑fast memory
* Pub/Sub
* Tool state
* Conversation state

### How Redis Runs

Redis is **not Docker** in production.

Electron spawns it directly:

```js
spawn('redis-server.exe', ['redis.conf'], {
  cwd: redisDataDir
})
```

Redis stores data here:

```
AppData/SparkAI/redis/
└── dump.rdb
```

### Order Matters

1️⃣ Redis starts first
2️⃣ Server connects to Redis
3️⃣ If Redis not ready → server waits/retries

Server never auto‑starts Redis.
Electron owns Redis.

---

## 6. Server Initialization Flow

### 6.1 How Server Is Started

Electron spawns embedded Python:

```js
spawn(pythonExe, ['main.py'], {
  env: {
    JARVIS_DATA_DIR: userDataDir,
    JARVIS_MODELS_DIR: path.join(userDataDir, 'models'),
    JARVIS_REDIS_URL: 'redis://127.0.0.1:6379'
  }
})
```

### 6.2 What Server Assumes

Server assumes:

* Redis already running
* Paths are provided via env vars
* Models may or may not exist

Server does **not**:

* Create OS folders
* Manage Redis lifecycle
* Assume install paths

---

## 7. Model Handling (Critical Design)

### 7.1 Models Are Data, Not Code

Models are **never bundled**.
They live only in:

```
AppData/SparkAI/models/
```

Server only loads models from this directory.

---

### 7.2 First‑Run Model Download

On first run:

* Server checks required models
* If missing → requests Electron
* Electron downloads models
* Progress shown in UI

Models download once.

---

### 7.3 Model Versioning

```
models/
└── whisper/
    ├── v1/
    ├── v2/
    └── active → v2
```

Updates:

* Only new versions download
* Old versions kept or cleaned safely

---

## 8. Server Internal Structure

Suggested structure:

```
jarvis‑core/
├── api/            ← FastAPI routes
├── core/           ← reasoning, planning
├── executor/       ← system actions
├── memory/         ← Redis abstraction
├── models/         ← model loaders
├── tools/          ← callable tools
└── main.py
```

Executor never runs blindly.
All actions are validated.

---

## 9. Permissions & Safety Model

Electron is the gatekeeper.

Flow:

1. Server requests an action
2. Electron checks OS + user permission
3. User approves or denies
4. Electron executes or rejects

Server never touches OS directly.

---

## 10. Normal Runtime Flow

```
User types → UI
UI → Server (WS)
Server → Redis
Server → Model
Server → Response
UI renders result
```

Everything stays local.
Latency is minimal.

---

## 11. App Update Flow

When app updates:

* Jarvis.exe replaced
* resources/app replaced
* AppData untouched

Result:

* Models remain
* Redis memory remains
* User data remains

No re‑download of models.

---

## 12. Desktop vs Mobile Strategy

### Desktop

* Local server
* Local Redis
* Local models
* Maximum speed

### Mobile (Future)

* Cloud‑hosted server
* Managed Redis
* Same API contracts

Server code stays the same.
Deployment changes only.

---

## 13. Development vs Production

### Development

* Docker allowed
* Hot reload
* Debug logging

### Production

* No Docker
* Standalone Redis
* Embedded Python

---

## 14. Mental Model (Final)

Electron = **OS + lifecycle manager**
Server = **brain**
Redis = **short‑term memory**
Models = **long‑term knowledge**

Replace the brain safely.
Never erase memory.

---

## 15. Why This Design Works

* Scales from laptop → cloud
* Update‑safe
* No vendor lock‑in
* Matches professional AI apps

This is production‑grade, not a prototype.
