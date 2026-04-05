# SparkAI TODO Execution

## Phase 1 — Data Storage Architecture
- [x] 1.1 Update `PathManager` — add `get_artifact_dir(kind, user_id)` helper
- [/] 1.2 Update `ArtifactStore` — human-readable artifact IDs (e.g. `document_weekly-plan`)
- [ ] 1.3 Add artifact kind config — which tools store artifacts and under what kind
- [ ] 1.4 Update `FileCreateTool` — redirect to artifacts + register via ArtifactStore
- [ ] 1.5 Move existing data to clean layout (models, db — no redownload)
- [ ] 1.6 Delete dead `tools_plugin` from AppData

## Phase 2 — Tool Docstrings (Task 4)
- [ ] 2.1 Add Inputs/Outputs docstrings: `screenshot.py`, `operations.py` (FileOpenTool, FileDeleteTool, FileMoveTool), `folder_organize.py` (FolderCleanupTool)

## Phase 3 — HOW_TO_ADD_TOOL.md (Task 5)
- [ ] 3.1 Create comprehensive guide at `server/tools/HOW_TO_ADD_TOOL.md`

## Phase 4 — Screenshot Fix (Task 1)
- [ ] 4.1 Test PowerShell screenshot snippet standalone
- [ ] 4.2 Fix if needed + add docstring

## Phase 5 — App Open Test (Task 3)
- [ ] 5.1 Test `app_open` with known target
