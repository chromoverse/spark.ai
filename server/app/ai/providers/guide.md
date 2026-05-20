# API Key Management Guide

## Storage Locations

| Location | Format | Purpose |
|----------|--------|---------|
| **Windows Registry** (HKCU\Environment) | `{username}:{ENV_NAME}` | Local persistence, survives reboots |
| **MongoDB** (users collection) | `api_keys.{provider}` | Cloud/mobile accessible, per-user |
| **In-memory** (_KeyCache) | `{env_name} → [keys]` | Runtime fast access, zero I/O |

## Registry Format

```
siddthecoder:GROQ_API_KEY = ["gsk_key1","gsk_key2"]
siddthecoder:GEMINI_API_KEY = "AIzaSy..."
siddthecoder:CEREBRAS_API_KEY = ["csk_key1","csk_key2"]
siddthecoder:SAMBANOVA_API_KEY = "4e3fd40c-..."
siddthecoder:MISTRAL_API_KEY = "ANJIR8wn..."
siddthecoder:OPENROUTER_API_KEY = "sk-or-..."
```

Single key = plain string. Multiple keys = JSON array.

## MongoDB Format

```json
{
  "_id": "ObjectId(...)",
  "username": "siddthecoder",
  "api_keys": {
    "groq": ["gsk_key1", "gsk_key2"],
    "gemini": ["AIzaSy..."],
    "cerebras": ["csk_key1"],
    "sambanova": ["4e3fd40c-..."],
    "mistral": ["ANJIR8wn..."],
    "openrouter": []
  }
}
```

## Supported Providers

| Provider | Env Name | Registry Key Example |
|----------|----------|---------------------|
| groq | `GROQ_API_KEY` | `siddthecoder:GROQ_API_KEY` |
| gemini | `GEMINI_API_KEY` | `siddthecoder:GEMINI_API_KEY` |
| openrouter | `OPENROUTER_API_KEY` | `siddthecoder:OPENROUTER_API_KEY` |
| cerebras | `CEREBRAS_API_KEY` | `siddthecoder:CEREBRAS_API_KEY` |
| sambanova | `SAMBANOVA_API_KEY` | `siddthecoder:SAMBANOVA_API_KEY` |
| mistral | `MISTRAL_API_KEY` | `siddthecoder:MISTRAL_API_KEY` |

## The ONE Function to Store Keys

```python
from app.ai.providers.key_manager import register_api_key_unified

await register_api_key_unified(
    username="siddthecoder",   # REQUIRED — scopes the registry key
    provider="cerebras",       # provider name (lowercase)
    keys=["key1", "key2"],     # single string or list
    user_id="abc123",          # optional — if given, saves to MongoDB too
)
```

This saves to **all three locations** (registry + mongo + memory) in one call.

## Bulk Registration

```python
from app.ai.providers.key_manager import register_all_keys_unified

await register_all_keys_unified(
    username="siddthecoder",
    keys_map={
        "groq": ["gsk_key1", "gsk_key2"],
        "cerebras": "csk_single_key",
        "mistral": ["key1", "key2"],
    },
    user_id="abc123",
)
```

## Reading Keys at Runtime

```python
from app.ai.providers.key_manager import get_all_keys, get_next_key

# Get all keys for a provider
keys = get_all_keys("groq")  # → ["gsk_key1", "gsk_key2"]

# Get next key in rotation (auto-rotates on each call)
key = get_next_key("groq")   # → "gsk_key1"
key = get_next_key("groq")   # → "gsk_key2"
key = get_next_key("groq")   # → "gsk_key1" (wraps)
```

## How Keys Load at Startup

1. `_KeyCache._bulk_load()` reads **all** `{username}:{ENV_NAME}` keys from Windows Registry
2. On user login, `activate_user_keys(user_id, user_data)` loads keys from MongoDB's `api_keys` dict into the priority layer
3. Priority: **user keys (from Mongo)** > **system keys (from registry)**

## API Routes

### POST `/auth/insert-api-keys`
```json
{
  "api_keys": {
    "groq": ["key1", "key2"],
    "cerebras": "single_key"
  }
}
```
Saves to both registry + MongoDB. Requires auth.

### PATCH `/auth/update-user-details?userId=...`
```json
{
  "api_keys": {
    "groq": ["key1"],
    "gemini": ["key1", "key2"]
  }
}
```
Same — syncs to registry + MongoDB.

## Migration (one-time)

```bash
cd server
python scripts/migrate_keys_to_unified.py
```

Moves old `groq_api_keys`/`gemini_api_keys` fields → `api_keys.groq`/`api_keys.gemini` in Mongo, and old unscoped registry keys → `username:ENV_NAME` format.

## Adding a New Provider in the Future

1. Add to `PROVIDER_ENV_MAP` in `key_manager.py`:
   ```python
   "newprovider": "NEWPROVIDER_API_KEY",
   ```
2. Create `newprovider_client.py` extending `BaseClient`
3. Add to `_ProviderRegistry._init_all()` in `router.py`
4. Add to `ROUTING_TABLE` in `routing_config.py`

No model changes needed — `api_keys` is a generic dict.
