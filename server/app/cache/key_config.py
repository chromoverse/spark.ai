from __future__ import annotations

import hashlib


def user_prefix(user_id: str) -> str:
    return f"user:{user_id}:"


def user_cache_prefix(user_id: str) -> str:
    return f"{user_prefix(user_id)}cache:"


def user_context_prefix(user_id: str) -> str:
    return f"{user_prefix(user_id)}ctx:"


def user_embedding_prefix(user_id: str  ) -> str:
    return f"{user_prefix(user_id)}emb:"


def user_details_key(user_id: str) -> str:
    return f"{user_prefix(user_id)}details"


def user_recent_messages_key(user_id: str) -> str:
    return f"{user_prefix(user_id)}recent_messages"


def user_cache_key(user_id: str, name: str) -> str:
    return f"{user_cache_prefix(user_id)}{name}"


def user_embedding_key(user_id: str, text_hash: str) -> str:
    return f"{user_embedding_prefix(user_id)}{text_hash}"


def user_context_key(
    user_id: str,
    query_hash: str,
    top_k: int,
    threshold: float,
    fast_lane: bool,
) -> str:
    rounded_threshold = round(float(threshold), 4)
    return (
        f"{user_context_prefix(user_id)}{query_hash}:"
        f"k{max(1, int(top_k))}:"
        f"t{rounded_threshold:.4f}:"
        f"f{int(bool(fast_lane))}"
    )


def user_sync_cursor_key(user_id: str) -> str:
    return f"{user_prefix(user_id)}sync:cursor"


def kernel_recent_events_key(user_id: str) -> str:
    return f"kernel:recent:{user_id}"


def query_hash(query: str) -> str:
    normalized = " ".join((query or "").strip().lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def try_extract_user_id(key: str) -> str | None:
    if not key.startswith("user:"):
        return None
    parts = key.split(":")
    if len(parts) < 2:
        return None
    user_id = parts[1].strip()
    return user_id or None
