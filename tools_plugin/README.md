# tools_plugin (Standalone Runtime Package)

This folder is the external seed source for runtime tools.

## Purpose
- Develop tools outside the server package.
- Sync this package to `AppData/Local/SparkAI/tools_plugin` at server startup.
- Keep runtime source of truth in AppData.

## Local Development
1. Run:
   - `pwsh ./setup_venv.ps1`
2. Activate:
   - `.\.venv\Scripts\Activate.ps1`
3. Validate:
   - `python tool_tester.py`

## Runtime Layout
- `manifest.json`
- `registry/tool_registry.json`
- `registry/tool_index.json`
- `tools/...`
- `automation/...`
- `utils/...`
- `manual.md`
- `tool_tester.py`
- `requirements.txt`

## Notes
- `requirements.txt` lists runtime dependencies required by tools.
- Server startup checks these requirements against the main server environment.
