"""Artifact retrieval tools — list, resolve, and open saved artifacts."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.path.artifacts import get_artifact_store
from app.plugins.tools.tool_base import BaseTool, ToolOutput


_TEXT_LIKE_EXTENSIONS = {".csv", ".ini", ".json", ".log", ".md", ".txt", ".yaml", ".yml"}
_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}

_ARTIFACT_KIND_ALIASES = {
    "doc": "document", "docs": "document", "document": "document", "documents": "document",
    "note": "document", "notes": "document", "text": "document", "texts": "document",
    "image": "screenshot", "images": "screenshot", "photo": "screenshot",
    "photos": "screenshot", "screenshot": "screenshot", "screenshots": "screenshot",
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
    *, artifact_id: Any, kind: Any, tool_name: Any, query: Any, latest: bool, user_id: str,
) -> Tuple[Optional[Any], Optional[Path], Optional[str]]:
    store = get_artifact_store()
    normalized_kind = _normalize_kind(kind)
    normalized_tool_name = str(tool_name or "").strip() or None
    normalized_query = str(query or "").strip()
    record = store.get_artifact(str(artifact_id).strip()) if artifact_id else None
    if record is None:
        items = []
        if normalized_query:
            items = store.search_artifacts(normalized_query, kind=normalized_kind, user_id=user_id, limit=10 if latest else 25)
            if normalized_tool_name:
                items = [item for item in items if item.tool_name == normalized_tool_name]
        else:
            items = store.list_artifacts(kind=normalized_kind, tool_name=normalized_tool_name, user_id=user_id, latest_only=latest, limit=1 if latest else 10)
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
    title = str(record.metadata.get("title", "")).strip() or str(record.metadata.get("label", "")).strip() or path.name
    return {
        "artifact_id": record.artifact_id, "kind": record.kind, "tool_name": record.tool_name,
        "title": title, "file_path": str(path), "mime_type": mime_type,
        "preview_kind": preview_kind, "preferred_app": _preferred_app_for_path(path, preview_kind),
        "size_bytes": int(record.size_bytes or path.stat().st_size), "created_at": record.created_at,
    }


class ArtifactListTool(BaseTool):
    """List saved artifacts such as screenshots."""

    TOOL_DESCRIPTION = "List saved artifacts such as screenshots"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "kind": {"type": "string", "required": False},
        "tool_name": {"type": "string", "required": False},
        "limit": {"type": "integer", "required": False, "default": 10},
        "latest_only": {"type": "boolean", "required": False, "default": False},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"artifacts": {"type": "array"}, "total": {"type": "integer"}, "kind": {"type": "string"}, "tool_name": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "show my latest screenshots", "inputs": {"kind": "screenshot"}}]
    SEMANTIC_TAGS = ["artifacts", "screenshots", "storage", "listing"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "artifact_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        kind = _normalize_kind(self.get_input(inputs, "kind", None))
        tool_name = self.get_input(inputs, "tool_name", None)
        latest_only = bool(self.get_input(inputs, "latest_only", False))
        limit = int(self.get_input(inputs, "limit", 10) or 10)
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        artifacts = get_artifact_store().list_artifacts(kind=kind, tool_name=tool_name, user_id=user_id, limit=limit, latest_only=latest_only)
        payload = [item.to_dict() for item in artifacts]
        return ToolOutput(success=True, data={"artifacts": payload, "total": len(payload), "kind": kind, "tool_name": tool_name})


class ArtifactResolveTool(BaseTool):
    """Resolve a saved artifact to a local path and viewer hints."""

    TOOL_DESCRIPTION = "Resolve a saved artifact to a local path and viewer hints"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "artifact_id": {"type": "string", "required": False},
        "kind": {"type": "string", "required": False},
        "latest": {"type": "boolean", "required": False, "default": True},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"artifact_id": {"type": "string"}, "kind": {"type": "string"}, "tool_name": {"type": "string"}, "title": {"type": "string"}, "file_path": {"type": "string"}, "mime_type": {"type": "string"}, "preview_kind": {"type": "string"}, "preferred_app": {"type": "string"}, "size_bytes": {"type": "integer"}, "created_at": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "resolve the latest screenshot", "inputs": {"kind": "screenshot", "latest": True}}]
    SEMANTIC_TAGS = ["artifacts", "screenshots", "documents", "resolve", "preview"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "artifact_resolve"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        artifact_id = self.get_input(inputs, "artifact_id", None)
        kind = _normalize_kind(self.get_input(inputs, "kind", None))
        tool_name = self.get_input(inputs, "tool_name", None)
        query = self.get_input(inputs, "query", None)
        latest = bool(self.get_input(inputs, "latest", True))
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        record, path, error = _resolve_artifact_record(artifact_id=artifact_id, kind=kind, tool_name=tool_name, query=query, latest=latest, user_id=user_id)
        if error or record is None or path is None:
            return ToolOutput(success=False, data={}, error=error or "No matching artifact found")
        return ToolOutput(success=True, data=_build_artifact_payload(record, path))


class ArtifactOpenTool(BaseTool):
    """Directly open a saved artifact on the current runtime machine."""

    TOOL_DESCRIPTION = "Directly open a saved artifact on the current runtime machine"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "artifact_id": {"type": "string", "required": False},
        "kind": {"type": "string", "required": False},
        "latest": {"type": "boolean", "required": False, "default": True},
        "app": {"type": "string", "required": False},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"artifact_id": {"type": "string"}, "kind": {"type": "string"}, "tool_name": {"type": "string"}, "title": {"type": "string"}, "file_path": {"type": "string"}, "mime_type": {"type": "string"}, "preview_kind": {"type": "string"}, "preferred_app": {"type": "string"}, "size_bytes": {"type": "integer"}, "created_at": {"type": "string"}, "opened_with": {"type": "string"}, "opened_at": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "open the latest screenshot right here", "inputs": {"kind": "screenshot", "latest": True}}]
    SEMANTIC_TAGS = ["artifacts", "screenshots", "open", "retrieval"]
    TOOL_CATEGORY = "spark_internal"

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
        record, path, error = _resolve_artifact_record(artifact_id=artifact_id, kind=kind, tool_name=tool_name, query=query, latest=latest, user_id=user_id)
        if error or record is None or path is None:
            return ToolOutput(success=False, data={}, error=error or "No matching artifact found")
        opened_with = await asyncio.to_thread(_open_path, str(path), app)
        payload = _build_artifact_payload(record, path)
        return ToolOutput(success=True, data={**payload, "opened_with": opened_with, "opened_at": datetime.now().isoformat()})


__all__ = ["ArtifactListTool", "ArtifactResolveTool", "ArtifactOpenTool"]
