
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

Proposed Structure
server/
├── app/
│   ├── features/
│   │   └── gmail/
│   │       ├── __init__.py
│   │       ├── auth.py          # OAuth flow, save/load tokens
│   │       ├── token_manager.py # get valid access_token (refresh logic)
│   │       └── router.py        # FastAPI routes: /gmail/connect, /gmail/callback
│   ├── core/
│   │   ├── encryption.py        # encrypt/decrypt refresh_token
│   │   └── token_cache.py       # in-memory access_token cache
│   └── db/
│       └── mongo.py             # DB connection
│
tools_plugin/
├── gmail/
│   ├── __init__.py
│   ├── read.py                  # list_emails(), get_email()
│   ├── send.py                  # send_email(), reply()
│   ├── organize.py              # label(), trash(), delete()
│   └── _client.py               # gets valid access_token from server, builds service

The Key Principle — Separation of Concerns
server/app/features/gmail/     →  "I own tokens, auth, security"
tools_plugin/gmail/            →  "I just DO things with Gmail, I don't care about tokens"
Tools should never handle tokens directly. They just call one function and get a ready-to-use Gmail service object.

How They Talk to Each Other
python# tools_plugin/gmail/_client.py
# This is the BRIDGE between tools and server

from app.features.gmail.token_manager import get_valid_access_token
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

async def get_gmail_service(user_id: str):
    """Tools call this — they get back a ready service, nothing else."""
    access_token = await get_valid_access_token(user_id)  # handles refresh internally
    creds = Credentials(token=access_token)
    return build('gmail', 'v1', credentials=creds)
python# tools_plugin/gmail/read.py
# Tool has zero knowledge of tokens

from ._client import get_gmail_service

async def list_emails(user_id: str, max_results: int = 10):
    service = await get_gmail_service(user_id)   # ← just this
    results = service.users().messages().list(
        userId='me', maxResults=max_results
    ).execute()
    return results.get('messages', [])
python# server/app/features/gmail/token_manager.py
# Server owns ALL token logic

from app.core.token_cache import get_cached, set_cached
from app.core.encryption import decrypt
from app.db.mongo import db
import httpx

async def get_valid_access_token(user_id: str) -> str:
    # 1. Check memory cache first
    token = get_cached(user_id, "gmail")
    if token:
        return token

    # 2. Pull refresh_token from MongoDB
    doc = await db.oauth_tokens.find_one({
        "user_id": user_id, "service": "gmail", "is_active": True
    })
    refresh_token = decrypt(doc["refresh_token"])

    # 3. Hit Google for new access_token
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        })
    data = resp.json()

    # 4. Cache it locally
    set_cached(user_id, "gmail", data["access_token"], data["expires_in"])
    return data["access_token"]
```

---

## Full Data Flow
```
LLM decides to read Gmail
        ↓
tools_plugin/gmail/read.py → list_emails(user_id)
        ↓
_client.py → get_gmail_service(user_id)
        ↓
token_manager.py → get_valid_access_token(user_id)
        ↓
  ┌─────────────────────────────────┐
  │  memory cache hit? → return it  │
  │  cache miss?                    │
  │    → MongoDB: get refresh_token │  ← cloud
  │    → Google: get access_token   │
  │    → cache it in memory         │  ← local
  └─────────────────────────────────┘
        ↓
Gmail API called ✅

Where Things Live
DataLocationWhyrefresh_tokenMongoDB (encrypted)Permanent, cross-deviceaccess_tokenMemory / token_cache.pyTemporary, 1hr, fastclient_secret.env on serverNever in code or DBcredentials.json.env vars onlyNever committed
This way your tools_plugin stays completely clean — tomorrow when you add Slack or Calendar tools, they follow the exact same pattern.