# 🧠 Jarvis Local-First AI Assistant — System Design

> **Goal**: Build a *Jarvis-like AI assistant* that installs with **one click**, runs **fully locally**, feels **instant**, and keeps **all intelligence on the user’s machine**.
> Docker is used **only for development**, **never required for end users**.

---

## 1️⃣ Core Philosophy (Non-Negotiable)

### 🔑 Local-First

* Jarvis **runs on the user’s machine**, not in the cloud
* Authentication (cloud or local) can be configured
* No mandatory internet (except optional LLM APIs)

### 🔑 Separation of Concerns

> **LLM THINKS**
> **CODE ACTS**
> **CLIENT DISPLAYS**

* LLMs never execute system code
* Server owns all business logic
* Client is a UI + local executor only

---

## 2️⃣ High-Level Architecture (Production)

```
┌──────────────────────────┐
│  Jarvis Desktop App      │
│  (Electron)              │
│                          │
│  - Chat UI               │
│  - Mic / TTS             │
│  - Status & Settings     │
│                          │
│   ┌──────────────────┐  │
│   │ Background Server │  │
│   │ (FastAPI Daemon)  │  │
│   └──────────────────┘  │
│            ↑ WS          │
│            ↓             │
│      Tools · Memory · AI │
└──────────────────────────┘
```

✔ Everything runs locally
✔ No Docker for users
✔ Near-zero latency

---

## 3️⃣ What Runs Where (Very Important)

| Component      | Runs Where     | Responsibility                             |
| -------------- | -------------- | ------------------------------------------ |
| Electron UI    | User machine   | UI, mic, TTS, display only                 |
| FastAPI Server | User machine   | **ALL logic, planning, memory, execution** |
| LLM            | Local or Cloud | Reasoning & planning only                  |
| Tools          | Local          | File system, OS actions                    |
| Database       | Local          | Memory, history, preferences               |

> ❗ The client **never decides logic** and **never plans tasks**.

---

## 4️⃣ Development vs Production

### 🧪 Development Mode

* Docker **allowed**
* Easier debugging
* Stable environment

```
docker compose up
```

### 🚀 Production Mode (Users)

* ❌ No Docker
* ❌ No terminal
* ✅ One-click install

---

## 5️⃣ Server Design (FastAPI Core)

The server is the **brain + hands** of Jarvis.

### Responsibilities

* Receive user input
* Decide intent (Planner)
* Select tools
* Execute tools safely
* Store memory
* Stream responses

### Internal Flow

```
User Input
   ↓
Planner (LLM → JSON intent)
   ↓
Permission Check
   ↓
Tool Executor
   ↓
Result Aggregation
   ↓
Final Response
```

---

## 6️⃣ Planner vs Executor (Critical Design)

### ❌ What NOT to do

* Send raw LLM output to client
* Let client "guess" what to execute

### ✅ Correct Pattern

**Planner output (structured):**

```json
{
  "tool": "filesystem.create_file",
  "args": {"path": "test.py", "content": ""}
}
```

**Executor (real Python code):**

```python
if tool == "filesystem.create_file":
    create_file(**args)
```

---

## 7️⃣ `client_core_demo` — What It SHOULD Become

### Current Problem

* `client_core_demo` is treated as a demo
* Logic is split unclearly

### Required Change

### ✅ **MERGE it into the server**

Do **NOT** keep it as a client executor. Server already runs locally and has OS access.

Rename it to:

```
app/tools/
```

This becomes the official **tool executor layer**.

---

## 8️⃣ Authentication

* You can keep cloud authentication (optional) for multi-device or remote features
* Server enforces permissions and execution rights
* Client only prompts user for confirmation

---

## 9️⃣ Database & Memory

### ❌ Not Mandatory

* MongoDB
* Cloud DB

### ✅ Recommended (Local)

* SQLite
* Local JSON
* Vector DB (later)

Memory lives in:

```
UserData/Jarvis/
 ├── memory.db
 ├── history.db
 └── config.json
```

---

## 🔟 Bundling Strategy (NO Docker for Users)

### Step 1️⃣ Bundle Server

Use **PyInstaller**:

```bash
pyinstaller --onefile main.py
```

Creates:

```
jarvis-core.exe
```

### Step 2️⃣ Electron App Layout

```
Jarvis/
 ├── Jarvis.exe          ← Electron
 ├── resources/
 │   ├── jarvis-core.exe
 │   ├── config.json
 │   └── tools/
```

### Step 3️⃣ Electron Starts Server

```js
spawn('jarvis-core.exe', { detached: true })
```

Server runs silently in background.

---

## 1️⃣1️⃣ Data Folder Management

Never store data inside install folder.

Use OS paths:

| OS      | Path                                 |
| ------- | ------------------------------------ |
| Windows | AppData/Local/Jarvis                 |
| macOS   | ~/Library/Application Support/Jarvis |
| Linux   | ~/.local/share/jarvis                |

Electron provides this path.

---

## 1️⃣2️⃣ WebSocket Contract

Client sends:

```json
{ "type": "user_input", "text": "Create file" }
```

Server sends:

```json
{ "type": "tool_call", "tool": "filesystem.create" }
```

Client responds:

```json
{ "type": "tool_result", "status": "ok" }
```

---

## 1️⃣3️⃣ Client Execution and Permissions

### ✅ Key Rule

* **Do NOT spawn a separate Python executor on the client**
* **React/Node cannot execute system tasks directly**
* **Client only asks for user confirmation and displays results**

### Permission Flow

```
User Input → Server Planner → Server checks permission → Server executes tool → Client displays / asks for confirmation
```

This ensures:

* Security
* Single source of execution
* Clear responsibility
* Local-first architecture

---

## 1️⃣4️⃣ Why This Design Works

* ⚡ Ultra-low latency
* 🔐 Privacy by default
* 🧠 Clear responsibility separation
* 🚀 Easy to scale later
* 🧩 OpenClaw-level architecture

---

## 1️⃣5️⃣ Future (Optional)

* Cloud sync
* Mobile client
* Multi-device memory
* Remote GPU LLMs

But **NOT required to function locally**.

---

## ✅ Final Rule

> **Ship ONE app.**
> **Hide the server.**
> **Keep everything local.**
> **Client asks for permission only; server executes all tasks.**
