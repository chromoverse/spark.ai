"""Artifact context service — provides recent artifact memory to the SQH prompt.

This service queries the ArtifactStore and builds a compact text block that
can be injected into the SQH prompt, giving the LLM awareness of recently
created files, screenshots, and documents.

Without this, the LLM has zero memory of what it created — so when the user
says "open the file you created about me", the SQH cannot resolve the reference.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


class ArtifactContextService:
    """Provide recent artifact context to the SQH prompt."""

    def get_recent_artifacts_context(
        self,
        user_id: str,
        limit: int = 5,
        max_bytes: int = 1500,
    ) -> str:
        """Return a compact text block listing recent artifacts for prompt injection.

        Example output::

            RECENT ARTIFACTS (created by previous tool executions):
            1. [document] "about me" → C:/.../documents/guest/about_me.txt (artifact_id=document_about-me-a3f2c1, tool=file_create)
            2. [screenshot] "desktop" → C:/.../screenshots/guest/spark_20260404.png (artifact_id=screenshot_desktop-b4e2a1, tool=screenshot_capture)
        """
        from app.path.artifacts import get_artifact_store

        store = get_artifact_store()
        artifacts = store.list_artifacts(user_id=user_id, limit=limit)
        if not artifacts:
            return ""

        lines = ["RECENT ARTIFACTS (created by previous tool executions):"]
        for i, record in enumerate(artifacts, 1):
            title = self._get_title(record)
            resolved_path = store.resolve_artifact_path(record)
            lines.append(
                f'{i}. [{record.kind}] "{title}" '
                f"→ {resolved_path} "
                f"(artifact_id={record.artifact_id}, tool={record.tool_name})"
            )

        text = "\n".join(lines)
        if len(text) > max_bytes:
            text = text[:max_bytes].rsplit("\n", 1)[0]
        return text

    def get_artifact_summary_for_tool(
        self,
        user_id: str,
        kind: Optional[str] = None,
        limit: int = 3,
    ) -> Dict[str, Any]:
        """Return structured recent artifact data for tool-level context injection."""
        from app.path.artifacts import get_artifact_store

        store = get_artifact_store()
        artifacts = store.list_artifacts(user_id=user_id, kind=kind, limit=limit)
        return {
            "count": len(artifacts),
            "items": [
                {
                    "artifact_id": r.artifact_id,
                    "kind": r.kind,
                    "title": self._get_title(r),
                    "file_path": str(store.resolve_artifact_path(r)),
                    "tool_name": r.tool_name,
                    "created_at": r.created_at,
                }
                for r in artifacts
            ],
        }

    @staticmethod
    def _get_title(record: Any) -> str:
        """Extract a human-readable title from an artifact record."""
        title = (
            str(record.metadata.get("title", "")).strip()
            or str(record.metadata.get("label", "")).strip()
        )
        if title:
            return title
        stem = Path(record.relative_path).stem
        return re.sub(r"[_\-]+", " ", stem).strip()


_artifact_context_service: Optional[ArtifactContextService] = None


def get_artifact_context_service() -> ArtifactContextService:
    global _artifact_context_service
    if _artifact_context_service is None:
        _artifact_context_service = ArtifactContextService()
    return _artifact_context_service
