## See parent CLAUDE.md

The authoritative project rules live in `../CLAUDE.md` at the project root.

Key reminders for this folder (`llms/` — local LLM client/runner):
- The combined graph is at `../graphify-out/` (NOT inside `llms/`).
- Read `../graphify-out/GRAPH_REPORT.md` first when answering codebase questions.
- This project is a **single git repo at the root**. The post-commit hook lives at
  `../.git/hooks/post-commit` and auto-rebuilds the graph after every commit — do
  not rebuild manually.
