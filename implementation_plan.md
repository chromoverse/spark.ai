# SparkAI Data Storage Architecture — Recommendation

## Current State (The Confusion)

You currently have **two locations** and no clear rule for which goes where:

| Location | What's there now |
|---|---|
| `~/AppData/Local/SparkAI/` | `db/` (LanceDB, SQLite kvstore), `memory/`, `models/` (whisper), `binaries/` (llama.cpp), `artifacts/` (screenshots), `logs/`, `tools_plugin/` (frozen copy) |
| `server/.sparkai_data/` | `artifacts/`, `logs/`, `memory/`, `models/` — mostly empty mirrors |

The `PathManager` tries `AppData/Local/SparkAI` first, and only falls back to `.sparkai_data` if AppData isn't writable. So `.sparkai_data` is a **fallback**, not a real store.

The problem is: when tools like `file_create` produce data (e.g., "create a weekly plan"), the LLM tells it to write wherever — often the server directory itself — because there's no canonical "tool output" location.

---

## Recommendation: Single Store, Clean Layout

**ONE place for all persistent data: `~/AppData/Local/SparkAI/`**

`server/.sparkai_data/` stays as a fallback only (for edge cases where AppData isn't writable). It should never be the primary target.

### Proposed Directory Layout

```
~/AppData/Local/SparkAI/                    ← USER_DATA_DIR (root)
│
├── config.json                             ← runtime config
│
├── db/                                     ← 🧠 ENGINE DATA (don't touch)
│   ├── kvstore.db                          ← SQLite key-value store
│   └── lanceData/                          ← LanceDB vector embeddings
│       └── user_queries.lance/
│
├── memory/                                 ← 🧠 ENGINE DATA
│   └── (conversation memory, context, etc.)
│
├── models/                                 ← 🧠 ENGINE DATA
│   └── whisper/                            ← downloaded ML models
│
├── binaries/                               ← 🧠 ENGINE DATA
│   └── llama-server.exe, etc.             ← llama.cpp runtime
│
├── artifacts/                              ← 📦 TOOL OUTPUT (all tool-produced files)
│   ├── records/                            ← JSON sidecar metadata (ArtifactRecord)
│   │   ├── screenshot_abc123.json
│   │   ├── document_def456.json
│   │   └── ...
│   ├── screenshots/                        ← screenshot images
│   │   └── <user_id>/
│   │       └── spark_screenshot_20260404.png
│   ├── documents/                          ← NEW: text files, plans, notes
│   │   └── <user_id>/
│   │       └── weekly_plan_20260404.txt
│   ├── exports/                            ← NEW: CSVs, reports, etc.
│   │   └── <user_id>/
│   └── media/                              ← NEW: generated audio, images
│       └── <user_id>/
│
├── logs/                                   ← 📋 RUNTIME LOGS
│   └── server-20260305.jsonl
│
└── tools_plugin/                           ← 🔧 FROZEN TOOL CODE (production only)
```

### The Key Principle

| Data Type | Where | Why |
|---|---|---|
| **Engine data** (vectors, sqlite, models, binaries) | `db/`, `memory/`, `models/`, `binaries/` | Machine-specific, not user-facing. Large, binary. |
| **Tool output** (screenshots, documents, plans, exports) | `artifacts/<kind>/<user_id>/` | User-facing files. Organized by kind. Indexed via `ArtifactRecord` JSON sidecars in `artifacts/records/`. |
| **Runtime state** (logs, config) | `logs/`, `config.json` | Operational. Rotatable. |
| **Tool code** (frozen plugin) | `tools_plugin/` | Production bundle only. |

---

## How It Works for Tools

### Every tool that produces a file does this:

```python
# 1. Get the right directory from PathManager
path_mgr = PathManager()
output_dir = path_mgr.get_artifact_dir("documents", user_id="guest")
# → ~/AppData/Local/SparkAI/artifacts/documents/guest/

# 2. Write the file
file_path = output_dir / "weekly_plan_20260404.txt"
file_path.write_text(content)

# 3. Register it as an artifact (so we can query it later)
from app.path.artifacts import get_artifact_store
artifact = get_artifact_store().register_file(
    kind="document",
    tool_name="file_create",
    file_path=file_path,
    user_id="guest",
    metadata={"title": "Weekly Plan", "format": "txt"}
)
# Returns artifact_id like "document_a1b2c3d4e5f6g7h8"
```

### Later, to fetch/query artifacts:

```python
store = get_artifact_store()

# Get all documents
docs = store.list_artifacts(kind="document", user_id="guest")

# Get latest screenshot
latest = store.list_artifacts(kind="screenshot", latest_only=True)

# Get by ID
record = store.get_artifact("screenshot_abc123def456")
file_path = store.resolve_artifact_path(record)
```

> [!IMPORTANT]
> The `ArtifactStore` + `ArtifactRecord` system **already exists** in your codebase (`app/path/artifacts.py`). It's currently only used by `ScreenshotCaptureTool`. The plan is to extend this pattern to ALL tools that produce files.

---

## What Changes in Code

### 1. `PathManager` — add artifact kind helper

Add a `get_artifact_dir(kind, user_id)` method that returns `artifacts/<kind>/<user_id>/` and ensures the directory exists.

### 2. `FileCreateTool` — use artifact system

When the LLM calls `file_create` and the path resolves inside the server directory (or is a relative/ambiguous path), redirect it to `artifacts/documents/<user_id>/` and register it as an artifact.

### 3. Other tools follow the same pattern

Any future tool that produces a file should use `get_artifact_dir(kind)` + `register_file()`.

---

## Why NOT `server/.sparkai_data/`?

| Concern | AppData/Local/SparkAI ✅ | server/.sparkai_data ❌ |
|---|---|---|
| Survives code updates / git clean | ✅ Outside repo | ❌ Inside repo |
| Works in production (frozen exe) | ✅ Standard OS path | ❌ Bundle is read-only |
| Works with multiple installs | ✅ Single user-scoped location | ❌ Per-checkout |
| User can find their files | ✅ Known Windows path | ❌ Hidden inside dev tree |
| `.gitignore` safe | ✅ Not in repo | ⚠️ Needs gitignore entry |

> [!NOTE]
> `server/.sparkai_data/` **stays as a fallback** — if AppData isn't writable (rare), the system gracefully degrades to writing there. No code change needed for this; `PathManager` already handles it.

---

## Open Question

> [!IMPORTANT]
> **Do you approve this layout?** Specifically:
> 1. All tool output goes to `~/AppData/Local/SparkAI/artifacts/<kind>/<user_id>/`
> 2. Engine data (db, models, binaries) stays where it is
> 3. `server/.sparkai_data/` remains as fallback only, not primary
> 4. Every file-producing tool registers via `ArtifactStore` for later retrieval
