# How To Add a Tool

This guide is the authoritative workflow for adding or updating a SparkAI
runtime tool.

## 1. Pick the implementation module

Place the tool in the correct package under `server/tools/tools/`:

- `system/`
- `file_system/`
- `web/`
- `ai/`
- `messaging/`

Keep related helpers in `server/tools/utils/` when the logic is shared by more
than one tool.

## 2. Implement the tool class

Every runtime tool must:

- Inherit `tools.tools.base.BaseTool`
- Implement `get_tool_name(self) -> str`
- Implement `_execute(self, inputs: dict[str, Any]) -> ToolOutput`

Basic shape:

```python
from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class MyTool(BaseTool):
    """Short purpose summary.

    Inputs:
    - foo (string, required)

    Outputs:
    - result (string)
    """

    def get_tool_name(self) -> str:
        return "my_tool"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        foo = self.get_input(inputs, "foo", "")
        if not foo:
            return ToolOutput(success=False, data={}, error="foo is required")

        return ToolOutput(success=True, data={"result": foo})
```

Implementation notes:

- Keep class docstrings concise but include `Inputs:` and `Outputs:` sections.
- Return structured `ToolOutput` data; avoid printing user-facing results from the tool itself.
- Use `self.get_input(...)` for optional fields and consistent defaults.
- Prefer existing shared helpers over duplicating OS logic.
- If the tool writes durable user-facing files, use the managed storage helpers in `app.path`.

## 3. Add the canonical registry entry

Edit:

- `server/tools/registry/tool_registry.json`

Each tool entry must define:

- `tool_name`
- `description`
- `execution_target`
- `params_schema`
- `output_schema`
- `module`
- `class_name`
- `metadata`
- `examples`

Rules:

- `tool_name` must exactly match `get_tool_name()`.
- `module` is relative to `server/tools/tools/`.
  Example: `system.screenshot`
- `class_name` must exactly match the Python class name.
- `examples` should include realistic user utterances and matching params.

### Approval and timeout defaults

Use `metadata` to describe default runtime controls when needed:

- `default_requires_approval`
- `default_approval_question`
- `default_timeout_ms`

Set approval defaults for destructive or user-sensitive actions.

## 4. Regenerate generated helper files

Do not hand-edit these files:

- `server/tools/manifest.json`
- `server/tools/registry/tool_index.json`

Regenerate them from `server/` after editing the registry:

```bash
python scripts/sync_index_manifest_with_registry.py
```

Validation-only mode:

```bash
python scripts/sync_index_manifest_with_registry.py --check
```

Current default exclusions are managed in:

- `server/scripts/sync_index_manifest_with_registry.py`

Use that script when a tool should stay in the full registry but be hidden from
generated helper files.

## 5. Validate the tool

Recommended checks from `server/`:

```bash
python -m tools.tool_tester --list
python -m tools.tool_tester --tool my_tool --inputs "{}"
python -m unittest testing.test_tool_registry_runtime
python scripts/sync_index_manifest_with_registry.py --check
```

Add or update focused tests when behavior changes. Good test targets include:

- happy-path execution
- validation failures
- approval-sensitive behavior
- path handling and artifact persistence
- registry/runtime integration when the tool affects loading or discovery

## 6. Artifact-producing tools

If the tool creates durable files the user may later open or retrieve:

- Write into the managed SparkAI storage root, not the repo tree.
- Prefer `PathManager().get_artifact_dir(kind, user_id)` for destination folders.
- Register the file with `ArtifactStore` from `app.path.artifacts`.

Example pattern:

```python
from pathlib import Path

from app.path.artifacts import get_artifact_store
from app.path.manager import PathManager

path_manager = PathManager()
output_dir = path_manager.get_artifact_dir("documents", user_id="guest")
file_path = output_dir / "note.txt"
file_path.write_text("hello", encoding="utf-8")

artifact = get_artifact_store().register_file(
    kind="document",
    tool_name="file_create",
    file_path=file_path,
    user_id="guest",
)
```

In the current implementation pass, artifact persistence is tool-local. The
execution engine does not automatically persist outputs from registry metadata.

## 7. Final checklist

- Tool implementation added in the correct `tools.tools.*` module
- `get_tool_name()` matches the registry
- Class docstring includes `Inputs:` and `Outputs:`
- `tool_registry.json` entry added or updated
- Generated files synced
- Focused tests added or updated
- Tool tester and registry checks pass
