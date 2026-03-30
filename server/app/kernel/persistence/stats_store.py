from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.plugins.tools.registry_loader import get_tool_registry
from app.db.mongo import get_db
from app.kernel.contracts.models import KernelEvent
from app.utils.path_manager import PathManager

logger = logging.getLogger(__name__)
_mongo_not_ready_warned = False


def _parse_window_days(window: str | int) -> int:
    if isinstance(window, int):
        return max(1, window)
    token = str(window).strip().lower()
    if token.endswith("d"):
        token = token[:-1]
    try:
        return max(1, int(token))
    except ValueError:
        return 30


class KernelStatsStore:
    """Mongo-backed storage and query service for kernel execution events."""

    async def persist_event(self, event: KernelEvent) -> None:
        try:
            db = get_db()
        except RuntimeError:
            global _mongo_not_ready_warned
            if not _mongo_not_ready_warned:
                logger.warning(
                    "Mongo not ready yet; skipping early stats events until DB startup completes"
                )
                _mongo_not_ready_warned = True
            else:
                logger.debug("Mongo not ready, skipping stats persist for event=%s", event.event_type)
            return

        ts = self._parse_event_time(event.timestamp)
        event_doc = event.to_dict()
        event_doc["created_at"] = ts

        await db.kernel_events.insert_one(event_doc)

        if event.event_type in {"task_started", "task_emitted", "task_completed", "task_failed"}:
            await self._upsert_task_run(db, event, ts)

        if event.event_type in {"tool_invoked", "tool_failed"} and event.tool_name:
            await self._insert_tool_invocation(db, event, ts)

    async def get_user_task_history(
        self,
        user_id: str,
        window: str | int = "90d",
        limit: int = 50,
        cursor: int = 0,
    ) -> Dict[str, Any]:
        db = get_db()
        since = datetime.now(timezone.utc) - timedelta(days=_parse_window_days(window))

        query = {"user_id": user_id, "updated_at": {"$gte": since}}
        docs = (
            await db.task_runs.find(query)
            .sort("updated_at", -1)
            .skip(max(0, cursor))
            .limit(max(1, min(limit, 200)))
            .to_list(length=max(1, min(limit, 200)))
        )

        items = [self._serialize_task_doc(doc) for doc in docs]
        return {
            "items": items,
            "next_cursor": cursor + len(items),
            "count": len(items),
        }

    async def get_user_metrics(self, user_id: str, window: str | int = "30d") -> Dict[str, Any]:
        db = get_db()
        since = datetime.now(timezone.utc) - timedelta(days=_parse_window_days(window))

        pipeline = [
            {"$match": {"user_id": user_id, "updated_at": {"$gte": since}}},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                }
            },
        ]

        rows = await db.task_runs.aggregate(pipeline).to_list(length=20)
        counts = {row["_id"]: row["count"] for row in rows}

        total = sum(counts.values())
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        success_rate = round((completed / total) * 100, 2) if total else 0.0

        return {
            "user_id": user_id,
            "window_days": _parse_window_days(window),
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "by_status": counts,
        }

    async def get_user_tool_metrics(
        self,
        user_id: str,
        window: str | int = "30d",
        limit: int = 10,
        sort: str = "score",
    ) -> Dict[str, Any]:
        db = get_db()
        since = datetime.now(timezone.utc) - timedelta(days=_parse_window_days(window))

        pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "created_at": {"$gte": since},
                }
            },
            {
                "$group": {
                    "_id": "$tool_name",
                    "invocations": {"$sum": 1},
                    "successes": {
                        "$sum": {
                            "$cond": [{"$eq": ["$success", True]}, 1, 0]
                        }
                    },
                    "avg_latency_ms": {"$avg": "$latency_ms"},
                    "p95_latency_ms": {"$max": "$latency_ms"},
                }
            },
        ]

        rows = await db.tool_invocations.aggregate(pipeline).to_list(length=500)
        scored = [self._score_tool_row(row) for row in rows]

        sort_key = {
            "success_rate": lambda r: r["success_rate"],
            "usage": lambda r: r["invocations"],
            "score": lambda r: r["weighted_score"],
        }.get(sort, lambda r: r["weighted_score"])

        scored.sort(key=sort_key, reverse=True)
        items = scored[: max(1, min(limit, 50))]

        return {
            "user_id": user_id,
            "window_days": _parse_window_days(window),
            "items": items,
            "count": len(items),
        }

    async def get_runtime_summary(self) -> Dict[str, Any]:
        registry = get_tool_registry()
        path_manager = PathManager()
        runtime_root = path_manager.get_tools_dir()
        runtime_manifest = path_manager.get_tools_manifest_file()
        manifest_version = "unknown"
        healthy = (
            runtime_root.exists()
            and runtime_manifest.exists()
            and path_manager.get_tools_registry_file().exists()
        )

        if runtime_manifest.exists():
            try:
                manifest_data = json.loads(runtime_manifest.read_text(encoding="utf-8"))
                manifest_version = str(manifest_data.get("version", "unknown"))
            except Exception:
                manifest_version = "invalid"

        return {
            "total_tools": len(registry.tools),
            "server_tools": len(registry.server_tools),
            "client_tools": len(registry.client_tools),
            "categories": list(registry.categories.keys()),
            "registry_path": registry.registry_path,
            "registry_version": registry.version,
            "runtime_manifest_version": manifest_version,
            "runtime_root": str(runtime_root),
            "runtime_mode": "direct_package",
            "runtime_source": "server/tools",
            "runtime_healthy": healthy,
        }

    async def _upsert_task_run(self, db, event: KernelEvent, ts: datetime) -> None:
        if not event.task_id:
            return

        query = {
            "user_id": event.user_id,
            "session_id": event.session_id,
            "task_id": event.task_id,
        }

        update_fields: Dict[str, Any] = {
            "user_id": event.user_id,
            "session_id": event.session_id,
            "request_id": event.request_id,
            "task_id": event.task_id,
            "tool_name": event.tool_name,
            "status": event.status or self._event_to_status(event.event_type),
            "updated_at": ts,
        }

        if event.event_type in {"task_started", "task_emitted"}:
            update_fields.setdefault("started_at", ts)
        if event.event_type in {"task_completed", "task_failed"}:
            update_fields["completed_at"] = ts
            if "duration_ms" in event.payload:
                update_fields["duration_ms"] = event.payload.get("duration_ms")
            if event.payload.get("error"):
                update_fields["error"] = event.payload.get("error")

        await db.task_runs.update_one(
            query,
            {
                "$set": update_fields,
                "$setOnInsert": {"created_at": ts},
            },
            upsert=True,
        )

    async def _insert_tool_invocation(self, db, event: KernelEvent, ts: datetime) -> None:
        assert event.tool_name is not None

        success = event.event_type == "tool_invoked"
        latency = event.payload.get("latency_ms")

        doc = {
            "user_id": event.user_id,
            "session_id": event.session_id,
            "request_id": event.request_id,
            "task_id": event.task_id,
            "tool_name": event.tool_name,
            "success": success,
            "latency_ms": latency,
            "error": event.payload.get("error"),
            "created_at": ts,
        }
        await db.tool_invocations.insert_one(doc)

        day_bucket = ts.strftime("%Y-%m-%d")
        update = {
            "$inc": {
                "invocations": 1,
                "successes": 1 if success else 0,
                "failures": 0 if success else 1,
            },
            "$set": {
                "tool_name": event.tool_name,
                "date": day_bucket,
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        }
        if isinstance(latency, (int, float)):
            update["$set"]["p95_latency_ms"] = latency

        await db.tool_daily_aggregates.update_one(
            {"tool_name": event.tool_name, "date": day_bucket},
            update,
            upsert=True,
        )

    @staticmethod
    def _serialize_task_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(doc)
        out["id"] = str(out.pop("_id", ""))
        for key in ("created_at", "updated_at", "started_at", "completed_at"):
            value = out.get(key)
            if isinstance(value, datetime):
                out[key] = value.isoformat()
        return out

    @staticmethod
    def _event_to_status(event_type: str) -> str:
        mapping = {
            "task_started": "running",
            "task_emitted": "emitted",
            "task_completed": "completed",
            "task_failed": "failed",
        }
        return mapping.get(event_type, "pending")

    @staticmethod
    def _parse_event_time(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _score_tool_row(row: Dict[str, Any]) -> Dict[str, Any]:
        invocations = int(row.get("invocations", 0) or 0)
        successes = int(row.get("successes", 0) or 0)
        success_rate = (successes / invocations) * 100 if invocations else 0.0

        p95 = float(row.get("p95_latency_ms") or 0.0)
        latency_score = 100.0 if p95 <= 0 else max(0.0, 100.0 - min(p95 / 50.0, 100.0))
        usage_score = min(100.0, invocations * 5.0)

        weighted_score = round(
            (success_rate * 0.60) + (latency_score * 0.25) + (usage_score * 0.15),
            2,
        )

        return {
            "tool_name": row.get("_id"),
            "invocations": invocations,
            "successes": successes,
            "failures": invocations - successes,
            "success_rate": round(success_rate, 2),
            "avg_latency_ms": round(float(row.get("avg_latency_ms") or 0.0), 2),
            "p95_latency_ms": round(p95, 2),
            "weighted_score": weighted_score,
        }


_stats_store: Optional[KernelStatsStore] = None


def get_kernel_stats_store() -> KernelStatsStore:
    global _stats_store
    if _stats_store is None:
        _stats_store = KernelStatsStore()
    return _stats_store



