from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

from app.cache.key_config import (
    try_extract_user_id,
    user_details_key,
    user_recent_messages_key,
    user_sync_cursor_key,
)
from app.config import settings

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Desktop local-first sync manager.

    - Writes are persisted to local sync outbox.
    - Background flusher pushes batched updates to cloud KV.
    - Reconciler periodically pulls cloud core state for active users.
    """

    _instance: Optional["SyncManager"] = None

    def __new__(cls) -> "SyncManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[attr-defined]
            return
        self._initialized = True  # type: ignore[attr-defined]
        self._running = False
        self._startup_once_done = False
        self._cache_manager: Any = None
        self._flush_task: Optional[asyncio.Task[Any]] = None
        self._reconcile_task: Optional[asyncio.Task[Any]] = None
        self._active_users: set[str] = set()
        self._seq = 0
        self._lock = asyncio.Lock()

    async def start(self, cache_manager: Any) -> None:
        if settings.environment != "DESKTOP":
            return
        if not bool(getattr(settings, "cache_sync_enabled", True)):
            return

        await cache_manager._ensure_client()
        self._cache_manager = cache_manager
        mode = self._sync_mode()

        if mode == "startup_once":
            if self._startup_once_done:
                return
            self._startup_once_done = True
            await self._startup_sync_once()
            return

        if self._running:
            return

        cloud = cache_manager.get_cloud_sync_client()
        if cloud is None:
            logger.info("🔁 SyncManager running in queue-only mode (no cloud KV sync client configured)")
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop(), name="cache_sync_flush")
        self._reconcile_task = asyncio.create_task(self._reconcile_loop(), name="cache_sync_reconcile")
        logger.info("🔁 SyncManager started (desktop local-first outbox sync)")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        tasks = [t for t in [self._flush_task, self._reconcile_task] if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._flush_task = None
        self._reconcile_task = None
        logger.info("🔁 SyncManager stopped")

    @staticmethod
    def _sync_mode() -> str:
        return str(getattr(settings, "cache_sync_mode", "background")).strip().lower()

    async def _startup_sync_once(self) -> None:
        local_kv = self._get_local_kv()
        cloud = self._get_cloud_client()
        if local_kv is None:
            logger.info("🔁 Startup sync skipped: local KV unavailable")
            return
        if cloud is None:
            logger.info("🔁 Startup sync skipped: no cloud KV sync client configured")
            return

        # Make sure unsynced local messages are represented in outbox.
        await self._enqueue_unsynced_recent_messages()

        max_batches = max(1, int(getattr(settings, "cache_sync_startup_max_batches", 50)))
        flushed = 0
        for _ in range(max_batches):
            processed = await self.flush_once()
            if processed <= 0:
                break
            flushed += processed

        remaining = await local_kv.get_sync_outbox_size()
        logger.info(
            "🔁 Startup one-shot sync finished (flushed=%s, pending_outbox=%s)",
            flushed,
            remaining,
        )

        if bool(getattr(settings, "cache_sync_close_after_startup", True)):
            try:
                await cloud.close()
                if self._cache_manager is not None:
                    self._cache_manager.cloud_sync_client = None
                logger.info("🔁 Cloud sync connection closed after startup sync")
            except Exception as exc:
                logger.debug("Failed to close cloud sync client: %s", exc)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def enqueue_user_details(self, user_id: str, details: dict[str, Any]) -> None:
        key = user_details_key(user_id)
        payload = {
            "updated_at": time.time(),
            "seq": self._next_seq(),
            "value": details,
        }
        await self._enqueue(scope="user_details", op="put", key=key, payload=payload, dedupe=True)

    async def enqueue_recent_messages(self, user_id: str, messages: list[dict[str, Any]]) -> None:
        key = user_recent_messages_key(user_id)
        payload = {
            "updated_at": time.time(),
            "seq": self._next_seq(),
            "messages": messages,
        }
        await self._enqueue(scope="recent_messages", op="put", key=key, payload=payload, dedupe=True)

    async def enqueue_recent_messages_if_needed(self, user_id: str, *, force: bool = False) -> bool:
        """
        Enqueue recent message sync only when local unsynced message count
        reaches a configured batch threshold, unless force=True.
        """
        local_kv = self._get_local_kv()
        if local_kv is None:
            return False

        threshold = max(1, int(getattr(settings, "cache_sync_message_batch_size", 10)))
        unsynced_count = await local_kv.get_unsynced_message_count(user_id)
        if (not force) and unsynced_count < threshold:
            return False

        recent_limit = max(10, int(getattr(settings, "cache_recent_messages_limit", 50)))
        recent_messages = await local_kv.get_messages(user_id, limit=recent_limit)
        await self.enqueue_recent_messages(user_id, recent_messages)
        return True

    async def enqueue_delete(self, scope: str, key: str) -> None:
        payload = {
            "updated_at": time.time(),
            "seq": self._next_seq(),
            "deleted": True,
        }
        await self._enqueue(scope=scope, op="delete", key=key, payload=payload, dedupe=True)

    async def _enqueue(
        self,
        *,
        scope: str,
        op: str,
        key: str,
        payload: dict[str, Any],
        dedupe: bool = True,
    ) -> None:
        if self._cache_manager is None:
            return
        local_kv = self._get_local_kv()
        if local_kv is None:
            return

        payload_json = json.dumps(payload, ensure_ascii=False)
        if dedupe:
            await local_kv.upsert_sync_event(scope, op, key, payload_json)
        else:
            await local_kv.enqueue_sync_event(scope, op, key, payload_json)
        user_id = try_extract_user_id(key)
        if user_id:
            self._active_users.add(user_id)

    async def _enqueue_unsynced_recent_messages(self) -> None:
        local_kv = self._get_local_kv()
        if local_kv is None:
            return
        user_ids = await local_kv.get_users_with_unsynced_messages()
        if not user_ids:
            return
        for user_id in user_ids:
            try:
                await self.enqueue_recent_messages_if_needed(user_id, force=True)
            except Exception as exc:
                logger.debug("Failed to enqueue unsynced recent messages for user=%s: %s", user_id, exc)

    def _get_local_kv(self) -> Any:
        if self._cache_manager is None:
            return None
        client = getattr(self._cache_manager, "client", None)
        try:
            from app.cache.local_kv_manager import LocalKVManager
            if isinstance(client, LocalKVManager):
                return client
        except Exception:
            return None
        return None

    def _get_cloud_client(self) -> Any:
        if self._cache_manager is None:
            return None
        return self._cache_manager.get_cloud_sync_client()

    async def _flush_loop(self) -> None:
        interval = max(0.2, float(getattr(settings, "cache_sync_flush_interval_ms", 2000)) / 1000.0)
        while self._running:
            try:
                await self.flush_once()
            except Exception as exc:
                logger.warning("Sync flush loop error: %s", exc)
            await asyncio.sleep(interval)

    async def _reconcile_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            try:
                await self.reconcile_once()
            except Exception as exc:
                logger.debug("Sync reconcile loop error: %s", exc)

    @staticmethod
    def _extract_message_ids(payload_json: str) -> list[str]:
        try:
            payload = json.loads(payload_json)
        except Exception:
            return []
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(messages, list):
            return []
        message_ids: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            mid = str(message.get("id", "")).strip()
            if mid:
                message_ids.append(mid)
        return message_ids

    async def flush_once(self) -> int:
        async with self._lock:
            local_kv = self._get_local_kv()
            cloud = self._get_cloud_client()
            if local_kv is None or cloud is None:
                return 0

            batch_size = max(1, int(getattr(settings, "cache_sync_batch_size", 100)))
            events = await local_kv.fetch_sync_events(limit=batch_size)
            if not events:
                return 0

            put_items: list[tuple[int, str, str, str]] = []
            delete_items: list[tuple[int, str]] = []
            for event in events:
                event_id = int(event["id"])
                scope = str(event.get("scope", "")).strip().lower()
                op = str(event.get("op", "")).strip().lower()
                key = str(event.get("key", ""))
                payload_json = str(event.get("payload_json", ""))
                if op == "delete":
                    delete_items.append((event_id, key))
                else:
                    put_items.append((event_id, scope, key, payload_json))

            success_ids: list[int] = []
            if put_items:
                try:
                    await cloud.bulk_set([(k, v, None) for _, _, k, v in put_items])
                    success_ids.extend([event_id for event_id, _, _, _ in put_items])

                    # Mark local messages as synced when recent_messages payload successfully lands in cloud.
                    message_ids_by_user: dict[str, set[str]] = {}
                    for _, scope, key, payload_json in put_items:
                        if scope != "recent_messages":
                            continue
                        user_id = try_extract_user_id(key)
                        if not user_id:
                            continue
                        message_ids = self._extract_message_ids(payload_json)
                        if not message_ids:
                            continue
                        bucket = message_ids_by_user.setdefault(user_id, set())
                        bucket.update(message_ids)
                    for user_id, message_ids in message_ids_by_user.items():
                        await local_kv.mark_messages_synced(user_id, sorted(message_ids))
                except Exception as exc:
                    error = str(exc)
                    for event_id, _, _, _ in put_items:
                        await local_kv.mark_sync_event_failure(event_id, error)

            if delete_items:
                try:
                    await cloud.delete(*[key for _, key in delete_items])
                    success_ids.extend([event_id for event_id, _ in delete_items])
                except Exception as exc:
                    error = str(exc)
                    for event_id, _ in delete_items:
                        await local_kv.mark_sync_event_failure(event_id, error)

            if success_ids:
                await local_kv.mark_sync_events_success(success_ids)
            return len(events)

    async def reconcile_once(self) -> None:
        if not self._active_users:
            return
        cloud = self._get_cloud_client()
        local_kv = self._get_local_kv()
        if cloud is None or local_kv is None:
            return

        for user_id in list(self._active_users):
            details_k = user_details_key(user_id)
            recent_k = user_recent_messages_key(user_id)
            cursor_k = user_sync_cursor_key(user_id)

            values = await cloud.bulk_get([details_k, recent_k])
            remote_details_raw, remote_recent_raw = values[0], values[1]

            cursor_raw = await local_kv.get(cursor_k)
            cursor = {}
            if cursor_raw:
                try:
                    cursor = json.loads(cursor_raw)
                except json.JSONDecodeError:
                    cursor = {}

            if remote_details_raw:
                try:
                    details_payload = json.loads(remote_details_raw)
                    remote_ts = float(details_payload.get("updated_at", 0) or 0)
                    local_ts = float(cursor.get("details_updated_at", 0) or 0)
                    if remote_ts > local_ts:
                        details = details_payload.get("value")
                        if isinstance(details, dict):
                            await self._cache_manager.set_user_details(user_id, details, sync=False)
                            cursor["details_updated_at"] = remote_ts
                except Exception:
                    pass

            if remote_recent_raw:
                try:
                    recent_payload = json.loads(remote_recent_raw)
                    remote_ts = float(recent_payload.get("updated_at", 0) or 0)
                    local_ts = float(cursor.get("messages_updated_at", 0) or 0)
                    if remote_ts > local_ts:
                        remote_messages = recent_payload.get("messages", [])
                        if isinstance(remote_messages, list):
                            await self._merge_remote_messages(user_id, remote_messages)
                            cursor["messages_updated_at"] = remote_ts
                except Exception:
                    pass

            if cursor:
                await local_kv.set(cursor_k, json.dumps(cursor, ensure_ascii=False))

    async def _merge_remote_messages(self, user_id: str, remote_messages: list[dict[str, Any]]) -> None:
        """
        Merge cloud messages into desktop SQLite history (best effort, idempotent).
        """
        local_kv = self._get_local_kv()
        if local_kv is None:
            return

        max_messages = max(10, int(getattr(settings, "cache_recent_messages_limit", 50)))
        local_messages = await local_kv.get_messages(user_id, limit=max_messages)
        seen = {
            f"{m.get('role','')}|{m.get('content','')}|{m.get('timestamp','')}"
            for m in local_messages
            if isinstance(m, dict)
        }

        inserted = 0
        for msg in remote_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            timestamp = str(msg.get("timestamp", ""))
            if not content:
                continue
            dedup = f"{role}|{content}|{timestamp}"
            if dedup in seen:
                continue
            message_id = str(msg.get("id") or f"{user_id}_{uuid.uuid4().hex[:12]}")
            ok = await local_kv.add_message(
                user_id=user_id,
                role=role,
                content=content,
                timestamp=timestamp or str(time.time()),
                message_id=message_id,
                is_synced=True,
            )
            if ok:
                inserted += 1
                seen.add(dedup)
        if inserted:
            logger.info("🔁 Reconciled %s remote messages into desktop cache for user %s", inserted, user_id)


_sync_manager: Optional[SyncManager] = None


def get_sync_manager() -> SyncManager:
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = SyncManager()
    return _sync_manager
