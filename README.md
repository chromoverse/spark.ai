Real-Time Voice Assistant – Low-Latency Architecture (RAG + Audio)
Goal

Design a voice assistant that feels instant:

User stops speaking → assistant responds in <500ms perceived latency
No blocking pipeline
Continuous streaming across all stages

Current Problem
The system is sequential, causing latency accumulation:

Audio → STT → (wait) → RAG → LLM → TTS → Audio Out

Key issues:
Waiting for final transcript before processing
RAG query triggered too late
LLM starts too late

2. Speculative RAG (Key Improvement)
Problem
RAG starts too late and blocks response.

Solution
Start retrieval before user finishes speaking.

Approach
Step 1: Incremental Query Extraction

From partial transcripts:

Extract keywords
Detect noun phrases
Build evolving query

Example:

"what is the capital of fr..."
→ query: "capital france"
Step 2: Parallel Vector Search
Fire async queries to vector DB
Update top-K results continuously
Step 3: Context Cache

Maintain in-memory:

current_context_candidates = top_k_results

When user stops:
→ context is already ready

3. RAG Optimization Strategies
A. Avoid Always Querying Vector DB

Use lightweight heuristics:

if short_query:
    skip RAG
elif no factual pattern:
    skip RAG
else:
    use RAG
B. Fast Similarity Gate
Compute embedding of query
Compare with recent queries (in-memory)
If similarity high → reuse previous context
C. Multi-Layer Retrieval
L1: In-memory cache (fastest)
L2: SQLite recent messages
L3: Vector DB (LanceDB)

Query in parallel, not sequentially.

D. Pre-Embedding

Precompute embeddings for:

recent chats
system prompts
frequent queries


7. End-of-Speech Prediction
Problem ( silero vad )

Waiting for silence timeout is slow.

Solution

Predict speech ending early using:

drop in audio energy
short pauses (~150ms)
punctuation prediction from STT

Trigger response slightly before full stop.

8. Prompt Construction Optimization
Problem

Prompt building delays LLM call.

Solution

Maintain incremental prompt state:

update prompt as transcript evolves
avoid rebuilding from scratch
9. Persistent LLM Session
Problem

Repeated cold starts.

Solution
reuse session/context window
maintain conversation state in memory
10. Latency Targets
Stage	Target Time
STT partial output	100–200ms
RAG ready	before user stops
LLM first token	150–300ms
First audio output	<500ms
11. Key Engineering Principles
Never wait for final input
Everything must be streaming
Everything must run in parallel
Predict instead of reacting
Cache aggressively
Prefer heuristics over LLM when possible









# Gmail (Multi-Service) OAuth Token Management
### Stack: FastAPI + MongoDB

A clean architecture for handling OAuth tokens across multiple services (Gmail, Slack, GitHub, etc.) with cloud persistence — so any user device can seamlessly authenticate.

---

## Core Concept

```
User Device (any)
  └── access_token       → memory only, short-lived (1hr)
      └── on expiry → fetch refresh_token from DB → get new access_token

Cloud MongoDB
  └── refresh_token      → encrypted at rest, permanent
```

---

## MongoDB Schema

One collection. One document per service per user.

```python
# Collection: oauth_tokens

{
  "_id":            ObjectId,
  "user_id":        "uuid-string",         # your app's user ID
  "service":        "gmail",               # 'gmail' | 'slack' | 'github' | ...
  "account_email":  "john@gmail.com",      # which account (supports multi-account)
  "refresh_token":  "ENCRYPTED_STRING",    # AES-256 encrypted, never plain text
  "scope":          "gmail.modify",        # what permissions were granted
  "is_active":      True,
  "connected_at":   datetime,
  "last_refreshed": datetime
}

# Compound index — one row per service per account per user
Index: { user_id: 1, service: 1, account_email: 1 }  # unique
```

---

## Project Structure

```
app/
├── main.py
├── core/
│   ├── encryption.py        # AES-256 encrypt/decrypt helpers
│   └── token_cache.py       # in-memory access_token cache (TTL-based)
├── db/
│   └── mongo.py             # MongoDB connection (Motor async client)
├── services/
│   └── oauth_token_service.py   # save, fetch, revoke tokens
├── routes/
│   ├── auth.py              # /auth/gmail/callback  → save token
│   └── gmail.py             # /gmail/messages       → use token
└── utils/
    └── google_client.py     # refresh access_token via Google API
```

---

## Key Flows

### 1. First Login — Save Token
```
POST /auth/gmail/callback?code=AUTH_CODE
  → exchange code with Google
  → receive { access_token, refresh_token, scope }
  → encrypt refresh_token
  → upsert into MongoDB (oauth_tokens)
  → cache access_token in memory (TTL 55min)
  → return success
```

### 2. Any Gmail API Call — Token Middleware
```
GET /gmail/messages
  → check memory cache for valid access_token
  → if expired or missing:
      → fetch encrypted refresh_token from MongoDB
      → decrypt it
      → POST to Google /oauth2/token
      → receive new access_token
      → update memory cache
  → call Gmail API with valid access_token
  → return data to client
```

### 3. New Device — No Re-Auth Needed
```
User logs in on mobile
  → your app authenticates user (JWT / session)
  → pull refresh_token from MongoDB (user already connected Gmail)
  → get fresh access_token from Google
  → ready to use Gmail API ✅
```

### 4. Disconnect a Service
```
DELETE /auth/gmail
  → set is_active = False in MongoDB
  → clear from memory cache
  → optionally: POST to Google /oauth2/revoke
```

---

## Encryption (Core Security Rule)

```python
# core/encryption.py — prototype

import os
from cryptography.fernet import Fernet

SECRET_KEY = os.getenv("TOKEN_ENCRYPTION_KEY")  # store in env, never hardcode
fernet = Fernet(SECRET_KEY)

def encrypt(plain_text: str) -> str:
    return fernet.encrypt(plain_text.encode()).decode()

def decrypt(cipher_text: str) -> str:
    return fernet.decrypt(cipher_text.encode()).decode()
```

> ⚠️ `TOKEN_ENCRYPTION_KEY` lives in `.env` / secrets manager — never in code or DB.

---

## Token Service (Prototype)

```python
# services/oauth_token_service.py

async def save_token(user_id, service, email, refresh_token, scope):
    await db.oauth_tokens.update_one(
        { "user_id": user_id, "service": service, "account_email": email },
        { "$set": {
            "refresh_token": encrypt(refresh_token),
            "scope": scope,
            "is_active": True,
            "connected_at": datetime.utcnow()
        }},
        upsert=True
    )

async def get_refresh_token(user_id, service, email=None):
    query = { "user_id": user_id, "service": service, "is_active": True }
    if email:
        query["account_email"] = email
    doc = await db.oauth_tokens.find_one(query)
    if not doc:
        raise Exception(f"No active {service} token for user {user_id}")
    return decrypt(doc["refresh_token"])

async def revoke_token(user_id, service):
    await db.oauth_tokens.update_one(
        { "user_id": user_id, "service": service },
        { "$set": { "is_active": False } }
    )
```

---

## In-Memory Access Token Cache

```python
# core/token_cache.py — prototype

from datetime import datetime, timedelta

_cache = {}  # { "user_id:service" : { token, expires_at } }

def get_cached(user_id, service):
    key = f"{user_id}:{service}"
    entry = _cache.get(key)
    if entry and entry["expires_at"] > datetime.utcnow():
        return entry["token"]
    return None

def set_cached(user_id, service, access_token, expires_in=3600):
    _cache[f"{user_id}:{service}"] = {
        "token": access_token,
        "expires_at": datetime.utcnow() + timedelta(seconds=expires_in - 60)
    }
```

> For multi-instance deployments, replace `_cache` dict with **Redis**.

---

## FastAPI Route (Prototype)

```python
# routes/gmail.py

@router.get("/gmail/messages")
async def list_messages(user_id: str):
    # 1. check cache
    access_token = get_cached(user_id, "gmail")

    # 2. refresh if needed
    if not access_token:
        refresh_token = await get_refresh_token(user_id, "gmail")
        access_token, expires_in = await refresh_access_token(refresh_token)
        set_cached(user_id, "gmail", access_token, expires_in)

    # 3. call Gmail API
    messages = await fetch_gmail_messages(access_token)
    return messages
```

---

## Environment Variables

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://yourapp.com/auth/gmail/callback

TOKEN_ENCRYPTION_KEY=...     # Fernet key — generate once, store safely
MONGO_URI=mongodb+srv://...
```

---

## Edge Cases to Handle

| Scenario | Response |
|---|---|
| `invalid_grant` from Google | Token revoked by user → set `is_active=False`, prompt re-auth |
| Google rotates refresh token | Update DB immediately with new refresh token |
| User connects 2nd Gmail account | New doc with different `account_email` — `UNIQUE` index handles it |
| Scale to multiple instances | Replace in-memory cache with Redis |
| Add a new service (Slack, etc.) | Just insert a new doc with `service: "slack"` — zero schema changes |

---

## Security Checklist

- [ ] Refresh tokens AES-256 encrypted at rest (Fernet)
- [ ] Encryption key stored in environment / secrets manager
- [ ] Access tokens never persisted to DB
- [ ] `is_active` flag for clean revocation
- [ ] Scopes stored — request only minimum required
- [ ] HTTPS enforced on all OAuth redirect URIs
- [ ] Token revocation endpoint exposed to users