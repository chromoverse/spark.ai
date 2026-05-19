## graphify — READ THIS FIRST

This project has a unified knowledge graph at `graphify-out/` covering all code folders:
`server/` (FastAPI backend), `electron/` (Electron UI), `voice_daemon/` (mic + wake word
daemon), and `llms/` (local LLM client/runner). Architecture, god nodes, and
cross-module relationships are already extracted.

The whole project is a **single git repository** (one `.git/` at the root). The
post-commit hook lives at `.git/hooks/post-commit` and rebuilds the graph in place.

### What you MUST do at the start of every session
1. Read `graphify-out/GRAPH_REPORT.md` before any other file. It is your map.
2. For "how does X relate to Y", use `graphify query "<question>"`,
   `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` — these traverse
   the graph for free (no LLM tokens).
3. The interactive visualization lives at `graphify-out/graph.html` (open it in a
   browser if you want a visual view).

### What you MUST NOT do
- **Do NOT run `graphify extract .`, `graphify .`, or `graphify update .`** unless
  the user explicitly asks. The graph is already built and is auto-rebuilt by the
  git post-commit hook.
- Do NOT re-read files that the graph already covers when answering questions about
  structure, dependencies, or where things live. Use the graph.
- Do NOT run `grep` / glob across the codebase before consulting the graph.

### Auto-update mechanism (already live)
- A single git post-commit hook at `.git/hooks/post-commit` rebuilds the graph
  (AST-only, free) after every commit, in the background. Log:
  `~/.cache/graphify-rebuild.log`.
- Manifest, graph, and report all live at the project root: `graphify-out/`.
- If the user changes code outside a commit and asks about it, run
  `graphify update .` (AST-only). Otherwise, trust the graph.

### Quick commands
```bash
# Ask a question of the graph
graphify query "How does the voice daemon talk to the server?"

# Find the shortest path between two symbols
graphify path "MainWindow" "APIRouter"

# Explain a concept / node
graphify explain "wake word detection"

# After non-commit edits, refresh AST-only
graphify update .
```
