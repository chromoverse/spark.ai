"""Artifact retrieval tools.

artifact_list:
- Purpose: list saved artifacts, usually screenshots, for the current user.
- Inputs: kind?, tool_name?, limit?, latest_only?
- Output: artifacts[], total, kind, tool_name.

artifact_open:
- Purpose: resolve a saved artifact and open it locally.
- Inputs: artifact_id?, kind?, latest?, app?
- Output: artifact_id, file_path, opened_with, opened_at.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List

from app.path.artifacts import get_artifact_store

from ..base import BaseTool, ToolOutput


def _open_path(path: str, app: str = "") -> str:
    if app:
        subprocess.Popen([app, path])
        return app
    if sys.platform == "win32":
        os.startfile(path)
        return "default"
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
        return "default"
    subprocess.Popen(["xdg-open", path])
    return "default"


class ArtifactListTool(BaseTool):
    """List durable artifact records filtered by kind/tool/user.

    Params:
    - kind: optional artifact kind such as "screenshot".
    - tool_name: optional tool filter such as "screenshot_capture".
    - limit: maximum number of records to return. Defaults to 10.
    - latest_only: when true, return only the newest matching record.
    - user_id: optional explicit user id. Usually injected by the runtime.

    Output:
    - artifacts: matching artifact records.
    - total: number of returned records.
    - kind: echoed filter value.
    - tool_name: echoed filter value.
    """

    def get_tool_name(self) -> str:
        return "artifact_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        kind = self.get_input(inputs, "kind", None)
        tool_name = self.get_input(inputs, "tool_name", None)
        latest_only = bool(self.get_input(inputs, "latest_only", False))
        limit = int(self.get_input(inputs, "limit", 10) or 10)
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        artifacts = get_artifact_store().list_artifacts(
            kind=kind,
            tool_name=tool_name,
            user_id=user_id,
            limit=limit,
            latest_only=latest_only,
        )
        payload = [item.to_dict() for item in artifacts]
        return ToolOutput(
            success=True,
            data={
                "artifacts": payload,
                "total": len(payload),
                "kind": kind,
                "tool_name": tool_name,
            }
        )


class ArtifactOpenTool(BaseTool):
    """Open a previously stored artifact by id or latest matching filter.

    Params:
    - artifact_id: optional exact artifact id to open.
    - kind: optional kind filter used when artifact_id is omitted.
    - latest: when true, open the newest matching artifact.
    - app: optional explicit app/executable to open the file with.
    - user_id: optional explicit user id. Usually injected by the runtime.

    Output:
    - artifact_id: id of the opened artifact.
    - file_path: resolved local file path.
    - opened_with: app used to open the file.
    - opened_at: ISO timestamp for the open action.
    """

    def get_tool_name(self) -> str:
        return "artifact_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        artifact_id = self.get_input(inputs, "artifact_id", None)
        kind = self.get_input(inputs, "kind", None)
        latest = bool(self.get_input(inputs, "latest", True))
        app = str(self.get_input(inputs, "app", "") or "").strip()
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        store = get_artifact_store()
        record = store.get_artifact(str(artifact_id).strip()) if artifact_id else None
        if record is None and latest:
            items = store.list_artifacts(kind=kind, user_id=user_id, latest_only=True)
            record = items[0] if items else None
        if record is None:
            return ToolOutput(success=False, data={}, error="No matching artifact found")

        path = store.resolve_artifact_path(record)
        if not path.exists():
            return ToolOutput(success=False, data={}, error=f"Artifact file missing: {path}")

        opened_with = _open_path(str(path), app=app)
        return ToolOutput(
            success=True,
            data={
                "artifact_id": record.artifact_id,
                "file_path": str(path),
                "opened_with": opened_with,
                "opened_at": datetime.now().isoformat(),
            }
        )


__all__ = [
    "ArtifactListTool",
    "ArtifactOpenTool",
]
