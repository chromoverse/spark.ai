from __future__ import annotations

import json
import mimetypes
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.path.manager import PathManager


@dataclass
class ArtifactRecord:
    """Durable metadata for one saved artifact file."""

    artifact_id: str
    kind: str
    tool_name: str
    task_id: str
    user_id: str
    created_at: str
    relative_path: str
    mime_type: str
    size_bytes: int
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    """Persist and query artifact metadata sidecars.

    Files stay in their managed artifact directories, while these JSON records
    make later lookup cheap for tools like `artifact_list` and `artifact_open`.

    Artifact IDs are human-readable slugs like ``document_weekly-plan`` or
    ``screenshot_desktop-20260404`` so they can be found via similarity search.
    """

    def __init__(self, path_manager: Optional[PathManager] = None):
        self.path_manager = path_manager or PathManager()

    def register_file(
        self,
        *,
        kind: str,
        tool_name: str,
        file_path: str | Path,
        user_id: str = "guest",
        task_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        artifact_id: Optional[str] = None,
        label: Optional[str] = None,
    ) -> ArtifactRecord:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Artifact file not found: {path}")

        effective_label = label or self._label_from_path(path)
        record = ArtifactRecord(
            artifact_id=artifact_id or self._new_artifact_id(kind, effective_label),
            kind=str(kind).strip() or "generic",
            tool_name=str(tool_name).strip() or "unknown_tool",
            task_id=str(task_id or "").strip(),
            user_id=str(user_id or "guest").strip() or "guest",
            created_at=datetime.now(timezone.utc).isoformat(),
            relative_path=self.path_manager.to_user_data_relative_path(path),
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            size_bytes=path.stat().st_size,
            metadata=dict(metadata or {}),
        )

        self._write_record(record)
        return record

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRecord]:
        record_path = self._record_path(artifact_id)
        if not record_path.exists():
            return None
        data = json.loads(record_path.read_text(encoding="utf-8"))
        return ArtifactRecord(**data)

    def list_artifacts(
        self,
        *,
        kind: Optional[str] = None,
        tool_name: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
        latest_only: bool = False,
    ) -> List[ArtifactRecord]:
        items: List[ArtifactRecord] = []
        records_dir = self.path_manager.get_artifact_records_dir()
        for record_path in records_dir.glob("*.json"):
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
                record = ArtifactRecord(**data)
            except Exception:
                continue

            if kind and record.kind != kind:
                continue
            if tool_name and record.tool_name != tool_name:
                continue
            if user_id and record.user_id != user_id:
                continue
            items.append(record)

        items.sort(key=lambda item: (item.created_at, item.artifact_id), reverse=True)
        if latest_only:
            return items[:1]
        return items[: max(1, int(limit or 10))]

    def search_artifacts(
        self,
        query: str,
        *,
        kind: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[ArtifactRecord]:
        """Search artifacts by keyword similarity across ID, kind, and metadata.

        This allows retrieval like "open the file you created about me" by
        matching query tokens against artifact_id, metadata title/description,
        and the original filename.
        """
        if not query:
            return self.list_artifacts(kind=kind, user_id=user_id, limit=limit)

        query_tokens = set(re.sub(r"[^a-z0-9]+", " ", query.lower()).split())
        if not query_tokens:
            return self.list_artifacts(kind=kind, user_id=user_id, limit=limit)

        scored: List[tuple[float, ArtifactRecord]] = []
        records_dir = self.path_manager.get_artifact_records_dir()
        for record_path in records_dir.glob("*.json"):
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
                record = ArtifactRecord(**data)
            except Exception:
                continue

            if kind and record.kind != kind:
                continue
            if user_id and record.user_id != user_id:
                continue

            # Build a searchable text blob from the record
            searchable_parts = [
                record.artifact_id.replace("-", " ").replace("_", " "),
                record.kind,
                record.tool_name,
                Path(record.relative_path).stem.replace("-", " ").replace("_", " "),
            ]
            for meta_val in record.metadata.values():
                if isinstance(meta_val, str):
                    searchable_parts.append(meta_val)
            searchable_blob = " ".join(searchable_parts).lower()
            searchable_tokens = set(re.sub(r"[^a-z0-9]+", " ", searchable_blob).split())

            matched = query_tokens & searchable_tokens
            if not matched:
                # Partial/substring match fallback
                partial_score = sum(
                    1 for qt in query_tokens
                    if any(qt in st or st in qt for st in searchable_tokens)
                )
                if partial_score == 0:
                    continue
                score = partial_score / len(query_tokens) * 0.5
            else:
                score = len(matched) / len(query_tokens)

            scored.append((score, record))

        scored.sort(key=lambda x: (-x[0], x[1].created_at), reverse=False)
        # Re-sort: highest score first, then newest first for ties
        scored.sort(key=lambda x: (-x[0], x[1].created_at), reverse=True)
        # Actually we want newest first among same score
        scored.sort(key=lambda x: -x[0])

        return [record for _, record in scored[:limit]]

    def resolve_artifact_path(self, record: ArtifactRecord) -> Path:
        relative = Path(record.relative_path)
        if relative.is_absolute():
            return relative
        return (self.path_manager.get_user_data_dir() / relative).resolve()

    def _write_record(self, record: ArtifactRecord) -> None:
        # Sidecar JSON keeps artifact lookup human-readable and easy to debug.
        record_path = self._record_path(record.artifact_id)
        record_path.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _record_path(self, artifact_id: str) -> Path:
        safe_id = self.path_manager._safe_path_token(artifact_id)
        return self.path_manager.get_artifact_records_dir() / f"{safe_id}.json"

    @staticmethod
    def _slugify(text: str, max_len: int = 40) -> str:
        """Convert free text to a filesystem-safe hyphenated slug."""
        slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
        if len(slug) > max_len:
            slug = slug[:max_len].rstrip("-")
        return slug or ""

    @staticmethod
    def _label_from_path(path: Path) -> str:
        """Derive a human-readable label from a file path stem."""
        stem = path.stem  # e.g. "weekly_plan_20260404"
        return stem.replace("_", " ").replace("-", " ").strip()

    @staticmethod
    def _new_artifact_id(kind: str, label: str = "") -> str:
        """Generate a human-readable artifact ID.

        Examples:
            _new_artifact_id("document", "weekly plan")  -> "document_weekly-plan"
            _new_artifact_id("screenshot", "desktop")    -> "screenshot_desktop-a3f2"
            _new_artifact_id("screenshot")               -> "screenshot_a1b2c3d4e5f6"
        """
        prefix = re.sub(r"[^a-z0-9]+", "_", str(kind or "artifact").strip().lower()).strip("_")
        slug = ArtifactStore._slugify(label)
        short_uuid = uuid.uuid4().hex[:6]

        if slug:
            candidate = f"{prefix}_{slug}"
        else:
            candidate = f"{prefix}_{uuid.uuid4().hex[:16]}"
            return candidate

        # Append short uuid to avoid collisions when label repeats
        return f"{candidate}-{short_uuid}"


_artifact_store: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    global _artifact_store
    if _artifact_store is None:
        _artifact_store = ArtifactStore()
    return _artifact_store
