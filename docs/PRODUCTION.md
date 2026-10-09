# PRODUCTION.md — Deploying the Brain & Shipping the Desktop App (v2)

Replaces the v1 local-server packaging blueprint (`legacy/PRODUCTION_v1.md`). Production comes
after R7. During the build, the same setup runs as a staging environment on free providers.

---

## 1. Brain deployment (VPS + Docker Compose)

### 1.1 Topology
```
Internet ──► Caddy (HTTPS, HTTP/2, WebSocket) ──► brain (uvicorn, N workers)
                                                   ├─► postgres:16 + pgvector (volume)
                                                   ├─► redis:7 (Socket.IO manager, cache, limits)
                                                   └─► searxng
```
- One VPS to start (4 vCPU / 8 GB), in the region chosen by the R0 benchmark.
- Socket.IO across multiple workers uses the Redis manager and websocket-only transport (no
  long-polling, so no sticky sessions); workers stay stateless.
- Embedding model (ONNX) loaded once per worker; CPU-only.

### 1.2 Files (`deploy/`)
`docker-compose.yml`, `Caddyfile`, `.env.example`, `backup.sh`, `docker-compose.test.yml`.

### 1.3 Release flow
1. CI on `main`: lint, type checks, unit + scenario + chaos suites, image build.
2. Tag `brain-vX.Y.Z` → CI pushes the image to GHCR.
3. On the VPS: `docker compose pull && docker compose up -d` with a health-gated rollout (`/ready`);
   `alembic upgrade head` runs as a one-shot container before the swap. Migrations are additive-first.
4. Rollback = previous image tag + the reversible migration.

### 1.4 Operations
| Area | Setup |
|---|---|
| Backups | nightly `pg_dump` to off-site object storage, 14 daily + 8 weekly; restore drill monthly |
| Secrets | `deploy/.env` with mode 600, root-only; rotation documented in `ENVIRONMENT.md` |
| Security | firewall (22 / 80 / 443 only), SSH keys only, unattended security updates, fail2ban |
| Monitoring | `/health` + `/ready` uptime checks; dashboards for first-audio latency, TTFT per chain entry, cache hits, tool errors, incidents, cost per user per day |
| Logs | JSON logs to file with 14-day rotation; secrets redacted at the formatter |
| Errors | Sentry (opt-in) for brain, Electron, body |
| Capacity triggers | p95 TTFT or CPU > 70% sustained → add workers; then a second VPS behind a load balancer with Redis/Postgres shared |

## 2. Desktop distribution

### 2.1 What ships
| Part | How |
|---|---|
| Electron app | electron-builder, **NSIS** installer (x64), Windows first |
| `spark-body` sidecar | embedded Python runtime + locked deps in `resources/body/`; spawned by Electron main |
| Wake word + VAD models, earcons | bundled |
| STT/TTS/local-LLM models | downloaded on first run per the fitness check / Models page (keeps the installer small) |

### 2.2 Behaviour
- Launch at login (setting on by default) and stay in the tray so the wake word keeps working.
- First run: sign in → fitness benchmark (~30–60 s) → permissions (mic) → optional Google connect.
- Auto-update via `electron-updater` + GitHub Releases (staged rollout), sidecar included.
- Code signing: Windows certificate (avoids SmartScreen warnings); macOS notarization when macOS ships.

### 2.3 Release checklist
```
[ ] TESTING.md matrix all green; chaos suite green
[ ] Latency bench: p50 < 1 s, p95 < 1.5 s on the reference laptop
[ ] Persona eval passed
[ ] Clean Windows 11 VM: install → sign in → benchmark → voice query → phone over USB
[ ] Auto-update from the previous version works
[ ] PRIVACY_POLICY.md current; CHANGELOG.md entry
[ ] Signed installer
[ ] Google OAuth verification / CASA status checked before opening Gmail to the public
```

## 3. Going from build to production
1. Paid providers: set `PAID_PROVIDERS_ENABLED=true` (Claude startup credits or budget), re-run evals,
   and confirm chain order.
2. Quotas per plan; usage page live.
3. Google OAuth verification + CASA done before Gmail opens to the public.
4. Privacy policy legally reviewed and published.
