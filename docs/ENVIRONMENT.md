# ENVIRONMENT.md — Setup & Environment Variables (v2)

v1 setup (server/, voice_daemon/, llms/) stays in the root `README.md` until those folders are deleted.

## 1. Prerequisites

- Windows 10/11 (primary desktop target); macOS/Linux fine for brain development
- Docker Desktop (Postgres + pgvector, Redis, SearXNG locally)
- Python 3.11+ with `uv`; Node.js 20+; Git
- Free accounts: Groq, NVIDIA Developer (build.nvidia.com), Cloudflare (Workers AI),
  Mistral (La Plateforme, Free mode with the training opt-out set), Google AI Studio (optional,
  trains on prompts), OpenRouter, Resend, Google Cloud OAuth client

## 2. Local dev

```bash
cp deploy/.env.example deploy/.env           # fill keys (section 3); the brain reads this file
# A) whole stack in Docker (the brain container runs migrations on start)
docker compose -f deploy/docker-compose.yml up -d --build
# B) or infra in Docker, brain with hot reload
docker compose -f deploy/docker-compose.yml up -d postgres redis searxng
cd brain && uv sync && uv run alembic upgrade head
cd brain && uv run uvicorn app.main:create_app --factory --reload --port 8080
# desktop
cd electron && npm ci && npm run dev
curl http://127.0.0.1:8080/health           # then sign in from the app (TESTING.md §8a)
```

Brain: `http://127.0.0.1:8080`. Renderer (Vite): `http://localhost:5123`.

**No cloud hosting needed during development.** The whole stack (brain, Postgres, Redis, SearXNG,
desktop app, body sidecar) runs on the laptop. Typical footprint: ~1.5 GB RAM for the containers and
brain, plus Electron and any local models. Free AI providers are called directly from the laptop.

**When you need a public URL** (a second device off your Wi-Fi, or OAuth providers that require an
HTTPS redirect such as Slack), expose the local brain with a free Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://127.0.0.1:8080
```
Use the printed `https://…trycloudflare.com` URL as `PUBLIC_URL` and in the provider's redirect
settings. Google OAuth works with `http://localhost` redirects in testing mode, so no tunnel is needed for it.

## 3. Variables

### 3.1 Brain (`deploy/.env`, read by `brain/app/core/config.py`)

| Variable | Required | Notes |
|---|---|---|
| `ENV` | yes | `dev` / `prod` |
| `PUBLIC_URL` | yes | e.g. `https://brain.example.com` (OAuth redirects) |
| `DATABASE_URL` | yes | `postgresql+asyncpg://…` |
| `REDIS_URL` | yes | `redis://redis:6379/0` |
| `JWT_SECRET` | yes | 64+ random bytes; rotate with `JWT_SECRET_PREVIOUS` |
| `ENCRYPTION_MASTER_KEY` | yes | 32-byte base64; encrypts BYOK + OAuth tokens. Losing it orphans them |
| `CORS_ORIGINS` | yes | app origins only, never `*` |
| `PAID_PROVIDERS_ENABLED` | yes | `false` during the build |
| `ALLOW_TRAINING_PROVIDERS_DEFAULT` | | `false`; the user can opt in |
| `GROQ_API_KEYS` | yes | comma-separated |
| `NVIDIA_API_KEYS` | | build.nvidia.com free endpoints |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKENS` | | Workers AI |
| `MISTRAL_API_KEYS` | | Free-mode credits; set the training opt-out in the console |
| `GEMINI_API_KEYS` | | only used for users who opt in to training providers |
| `OPENROUTER_API_KEYS` | | `:free` models |
| `ANTHROPIC_API_KEY` | later | only read when `PAID_PROVIDERS_ENABLED=true` |
| `SEARXNG_URL` | yes | `http://searxng:8080` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | yes | sign-in + Gmail/Calendar/Drive; add beta users as test users |
| `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET` | R4 | |
| `RESEND_API_KEY`, `MAIL_FROM` | yes | OTP email |
| `OBJECT_STORE_*` | R4 | artifacts/uploads (local disk in dev; S3-compatible in prod) |
| `SENTRY_DSN` | prod | opt-in error reporting |

**Groq Orpheus TTS:** before the API works, open the Groq console playground for
`canopylabs/orpheus-v1-english` and accept the model terms for your organization.

### 3.2 Electron (`electron/.env`, never committed)

| Variable | Notes |
|---|---|
| `VITE_BRAIN_URL` | read by the main process; defaults to `http://127.0.0.1:8080` (public value, no secrets) |
| `SPARK_BODY_PYTHON` | dev only: interpreter for the sidecar (defaults to `body/.venv`) |
| `ELECTRON_SAFE_GPU_MODE` | `1` disables GPU acceleration |

### 3.3 Body (`spark-body`)
No secrets on disk. Configuration comes from the brain (`settings.changed`, engine plan) and the
local `%LOCALAPPDATA%\SparkAI\config.json` (mic device, wake word sensitivity).
- **Platform keys never leave the brain.** Cloud voice engines on platform keys (Groq Orpheus,
  Groq Whisper) are called through the brain's streaming proxy (`API.md` §2.5).
- **The user's own keys** may be sent to that user's device for the session (memory only) so the
  device can call the provider directly and save the proxy hop. The fitness check measures both paths.
- edge-tts needs no key and always runs on the device.

## 4. Secrets handling

Real values only in `deploy/.env` (git-ignored) or the VPS secret store; `.env.example` holds
placeholders. Rotate anything that was ever committed or pasted. Keys are never logged or sent to the model.

## 5. Ports (dev)

| Port | Service |
|---|---|
| 8080 | brain (HTTP + Socket.IO) |
| 5123 | Vite renderer |
| 5432 / 6379 | Postgres / Redis |
| 8888 | SearXNG (host mapping) |
| 9001 | local llama.cpp server (body, when used) |
| 9222 | Chrome CDP (browser hands) |
