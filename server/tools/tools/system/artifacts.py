"""Artifact retrieval tools.

artifact_list:
- Purpose: list saved artifacts, usually screenshots, for the current user.
- Inputs: kind?, tool_name?, limit?, latest_only?
- Outputs: artifacts[], total, kind, tool_name.

artifact_resolve:
- Purpose: resolve a saved artifact to a local path plus open/preview hints.
- Inputs: artifact_id?, kind?, tool_name?, query?, latest?
- Outputs: artifact_id, file_path, mime_type, preview_kind, preferred_app.

artifact_open:
- Purpose: resolve a saved artifact and open it locally.
- Inputs: artifact_id?, kind?, latest?, app?
- Outputs: artifact_id, file_path, opened_with, opened_at.
"""

from __future__ import annotations

import mimetypes
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.path.artifacts import get_artifact_store

from ..base import BaseTool, ToolOutput


_TEXT_LIKE_EXTENSIONS = {
    ".csv",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
}

_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}

_ARTIFACT_KIND_ALIASES = {
    "doc": "document",
    "docs": "document",
    "document": "document",
    "documents": "document",
    "note": "document",
    "notes": "document",
    "text": "document",
    "texts": "document",
    "image": "screenshot",
    "images": "screenshot",
    "photo": "screenshot",
    "photos": "screenshot",
    "screenshot": "screenshot",
    "screenshots": "screenshot",
}


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


def _normalize_kind(kind: Any) -> Optional[str]:
    text = str(kind or "").strip().lower()
    if not text:
        return None
    return _ARTIFACT_KIND_ALIASES.get(text, text)


def _resolve_artifact_record(
    *,
    artifact_id: Any,
    kind: Any,
    tool_name: Any,
    query: Any,
    latest: bool,
    user_id: str,
) -> Tuple[Optional[Any], Optional[Path], Optional[str]]:
    store = get_artifact_store()
    normalized_kind = _normalize_kind(kind)
    normalized_tool_name = str(tool_name or "").strip() or None
    normalized_query = str(query or "").strip()
    record = store.get_artifact(str(artifact_id).strip()) if artifact_id else None
    if record is None:
        items = []
        if normalized_query:
            items = store.search_artifacts(
                normalized_query,
                kind=normalized_kind,
                user_id=user_id,
                limit=10 if latest else 25,
            )
            if normalized_tool_name:
                items = [item for item in items if item.tool_name == normalized_tool_name]
        else:
            items = store.list_artifacts(
                kind=normalized_kind,
                tool_name=normalized_tool_name,
                user_id=user_id,
                latest_only=latest,
                limit=1 if latest else 10,
            )
        record = items[0] if items else None
    if record is None:
        return None, None, "No matching artifact found"

    path = store.resolve_artifact_path(record)
    if not path.exists():
        return None, None, f"Artifact file missing: {path}"

    return record, path, None


def _guess_preview_kind(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()
    if str(mime_type or "").startswith("image/") or suffix in _IMAGE_EXTENSIONS:
        return "image"
    if str(mime_type or "").startswith("text/") or suffix in _TEXT_LIKE_EXTENSIONS:
        return "text"
    if suffix == ".pdf":
        return "pdf"
    return "file"


def _preferred_app_for_path(path: Path, preview_kind: str) -> str:
    if sys.platform == "win32" and (preview_kind == "text" or path.suffix.lower() in _TEXT_LIKE_EXTENSIONS):
        return "notepad"
    return ""


def _build_artifact_payload(record: Any, path: Path) -> Dict[str, Any]:
    mime_type = str(record.mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    preview_kind = _guess_preview_kind(path, mime_type)
    title = (
        str(record.metadata.get("title", "")).strip()
        or str(record.metadata.get("label", "")).strip()
        or path.name
    )
    return {
        "artifact_id": record.artifact_id,
        "kind": record.kind,
        "tool_name": record.tool_name,
        "title": title,
        "file_path": str(path),
        "mime_type": mime_type,
        "preview_kind": preview_kind,
        "preferred_app": _preferred_app_for_path(path, preview_kind),
        "size_bytes": int(record.size_bytes or path.stat().st_size),
        "created_at": record.created_at,
    }


class ArtifactListTool(BaseTool):
    """List saved artifacts for the current user.

    Inputs:
    - kind (string, optional): artifact kind such as "screenshot" or "document"
    - tool_name (string, optional): producing tool name such as "screenshot_capture"
    - limit (integer, optional): maximum number of records to return (default 10)
    - latest_only (boolean, optional): when true, return only the newest matching record
    - user_id (string, optional): explicit user id, usually injected by the runtime

    Outputs:
    - artifacts (array): matching artifact records
    - total (integer): number of returned records
    - kind (string): echoed filter value
    - tool_name (string): echoed filter value
    """

    def get_tool_name(self) -> str:
        return "artifact_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        kind = _normalize_kind(self.get_input(inputs, "kind", None))
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


class ArtifactResolveTool(BaseTool):
    """Resolve a saved artifact without opening it.

    Inputs:
    - artifact_id (string, optional): exact artifact id to resolve
    - kind (string, optional): artifact kind filter used when artifact_id is omitted
    - tool_name (string, optional): producing tool name filter such as "file_create"
    - query (string, optional): fuzzy search text such as "about me" or "weekly plan"
    - latest (boolean, optional): when true, resolve the newest matching artifact
    - user_id (string, optional): explicit user id, usually injected by the runtime

    Outputs:
    - artifact_id (string): id of the resolved artifact
    - kind (string): artifact kind
    - tool_name (string): tool that created the artifact
    - title (string): human-readable artifact label
    - file_path (string): resolved local file path
    - mime_type (string): guessed MIME type
    - preview_kind (string): "image", "text", "pdf", or "file"
    - preferred_app (string): suggested local app, empty when default association is preferred
    - size_bytes (integer): file size in bytes
    - created_at (string): artifact record timestamp
    """

    def get_tool_name(self) -> str:
        return "artifact_resolve"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        artifact_id = self.get_input(inputs, "artifact_id", None)
        kind = _normalize_kind(self.get_input(inputs, "kind", None))
        tool_name = self.get_input(inputs, "tool_name", None)
        query = self.get_input(inputs, "query", None)
        latest = bool(self.get_input(inputs, "latest", True))
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        record, path, error = _resolve_artifact_record(
            artifact_id=artifact_id,
            kind=kind,
            tool_name=tool_name,
            query=query,
            latest=latest,
            user_id=user_id,
        )
        if error or record is None or path is None:
            return ToolOutput(success=False, data={}, error=error or "No matching artifact found")

        return ToolOutput(success=True, data=_build_artifact_payload(record, path))


class ArtifactOpenTool(BaseTool):
    """Open a previously stored artifact by id or latest matching filter.

    Inputs:
    - artifact_id (string, optional): exact artifact id to open
    - kind (string, optional): artifact kind filter used when artifact_id is omitted
    - tool_name (string, optional): producing tool name filter such as "file_create"
    - query (string, optional): fuzzy search text such as "about me" or "weekly plan"
    - latest (boolean, optional): when true, open the newest matching artifact
    - app (string, optional): explicit app/executable to open the file with
    - user_id (string, optional): explicit user id, usually injected by the runtime

    Outputs:
    - artifact_id (string): id of the opened artifact
    - file_path (string): resolved local file path
    - mime_type (string): guessed MIME type
    - preview_kind (string): "image", "text", "pdf", or "file"
    - preferred_app (string): suggested local app when default association is not ideal
    - opened_with (string): app used to open the file
    - opened_at (string): ISO timestamp for the open action
    """

    def get_tool_name(self) -> str:
        return "artifact_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        artifact_id = self.get_input(inputs, "artifact_id", None)
        kind = _normalize_kind(self.get_input(inputs, "kind", None))
        tool_name = self.get_input(inputs, "tool_name", None)
        query = self.get_input(inputs, "query", None)
        latest = bool(self.get_input(inputs, "latest", True))
        app = str(self.get_input(inputs, "app", "") or "").strip()
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        record, path, error = _resolve_artifact_record(
            artifact_id=artifact_id,
            kind=kind,
            tool_name=tool_name,
            query=query,
            latest=latest,
            user_id=user_id,
        )
        if error or record is None or path is None:
            return ToolOutput(success=False, data={}, error=error or "No matching artifact found")

        opened_with = _open_path(str(path), app=app)
        payload = _build_artifact_payload(record, path)
        return ToolOutput(
            success=True,
            data={**payload, "opened_with": opened_with, "opened_at": datetime.now().isoformat()}
        )


__all__ = [
    "ArtifactListTool",
    "ArtifactResolveTool",
    "ArtifactOpenTool",
]
