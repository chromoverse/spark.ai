from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.api.deps import Db, Me, Rt
from app.artifacts import store
from app.core.errors import BAD_INPUT, NOT_FOUND, ApiError, ok
from app.db.models import Artifact

router = APIRouter(prefix="/v2")

MAX_UPLOAD = 20 * 1024 * 1024
KINDS = {"text", "file", "image", "table"}


def _artifact(rt: Any, a: Artifact) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "kind": a.kind,
        "name": a.name,
        "mime": a.mime,
        "size": a.size,
        "preview": a.preview,
        "thread_id": str(a.thread_id) if a.thread_id else None,
        "job_id": str(a.job_id) if a.job_id else None,
        "device_id": str(a.device_id) if a.device_id else None,
        "created_at": a.created_at.isoformat(),
        "url": store.signed_url(rt, a.id),
    }


RAW_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.post("/uploads", openapi_extra=RAW_BODY)
async def upload(
    request: Request,
    me: Me,
    rt: Rt,
    name: str = Query(min_length=1, max_length=200),
    kind: str = Query("file"),
) -> dict[str, Any]:
    """A file from a device (raw body, ≤ 20 MB) becomes an artifact: handoffs, large outputs."""
    if kind not in KINDS:
        raise ApiError("invalid_input", BAD_INPUT)
    data = await request.body()
    if not data or len(data) > MAX_UPLOAD:
        raise ApiError("invalid_input", "That file is empty or bigger than 20 MB.")
    mime = request.headers.get("content-type", "application/octet-stream")[:100]
    from app.agent import context

    ctx = await context.load(rt, me.user_id, me.device_id)
    art = await store.save(
        rt,
        me.user_id,
        data,
        name=name,
        kind=kind,
        mime=mime,
        thread_id=ctx.thread_id,
        device_id=me.device_id,
        preview={"text": data[:200].decode("utf-8", "replace")} if mime.startswith("text/") else {},
    )
    return ok(_artifact(rt, art))


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: uuid.UUID, me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    art = await db.scalar(
        select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == me.user_id)
    )
    if art is None:
        raise ApiError("not_found", NOT_FOUND)
    return ok(_artifact(rt, art))


@router.get("/artifacts/{artifact_id}/download")
async def download(
    artifact_id: uuid.UUID, rt: Rt, db: Db, exp: int = Query(), sig: str = Query(max_length=64)
) -> Response:
    """No token: the signature (HMAC over id + expiry, 1 h) is the permission (§26.4-G)."""
    if not store.valid(rt, artifact_id, exp, sig):
        raise ApiError("not_found", NOT_FOUND)
    art = await db.scalar(select(Artifact).where(Artifact.id == artifact_id))
    if art is None:
        raise ApiError("not_found", NOT_FOUND)
    data = await asyncio.to_thread(store.path_of(rt, art).read_bytes)
    safe = "".join(c for c in art.name if c.isalnum() or c in " ._-")[:100] or "download"
    return Response(
        data,
        media_type=art.mime,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )
