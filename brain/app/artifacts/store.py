"""Artifacts (REDESIGN §22.3, §26.4-G): a row per artifact, bytes on disk under ARTIFACTS_DIR, and
signed download URLs a device can open without its token (HMAC over id + expiry).

ponytail: local disk on the brain host; object storage when the brain runs on more than one box."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from pathlib import Path
from typing import Any

from app.core.runtime import Runtime
from app.db.base import uuid7
from app.db.models import Artifact
from app.gateway import push

URL_TTL_S = 3600
PREVIEW_CHARS = 280


def _dir(rt: Runtime) -> Path:
    path = Path(rt.settings.artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_of(rt: Runtime, art: Artifact) -> Path:
    return _dir(rt) / art.storage_ref


def _key(rt: Runtime) -> bytes:
    secret = rt.settings.jwt_secret.get_secret_value().encode()
    return hmac.new(secret, b"spark-artifact-url", hashlib.sha256).digest()


def sign(rt: Runtime, artifact_id: uuid.UUID, exp: int) -> str:
    return hmac.new(_key(rt), f"{artifact_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def signed_url(rt: Runtime, artifact_id: uuid.UUID) -> str:
    exp = int(rt.clock.now().timestamp()) + URL_TTL_S
    base = rt.settings.public_url.rstrip("/")
    return f"{base}/v2/artifacts/{artifact_id}/download?exp={exp}&sig={sign(rt, artifact_id, exp)}"


def valid(rt: Runtime, artifact_id: uuid.UUID, exp: int, sig: str) -> bool:
    if exp < rt.clock.now().timestamp():
        return False
    return hmac.compare_digest(sign(rt, artifact_id, exp), sig)


async def save(
    rt: Runtime,
    user_id: uuid.UUID,
    data: bytes,
    *,
    name: str,
    kind: str,
    mime: str,
    thread_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    preview: dict[str, Any] | None = None,
) -> Artifact:
    """Stores the bytes, records the row, and tells every device (`artifact.new`)."""
    art_id = uuid7()
    ref = f"{art_id}.bin"
    await asyncio.to_thread((_dir(rt) / ref).write_bytes, data)
    art = Artifact(
        id=art_id,
        user_id=user_id,
        thread_id=thread_id,
        job_id=job_id,
        device_id=device_id,
        kind=kind,
        name=name[:200],
        mime=mime,
        size=len(data),
        storage_ref=ref,
        preview=preview or {},
    )
    async with rt.db() as db:
        db.add(art)
        ev = await push.record(
            rt,
            db,
            user_id,
            "artifact.new",
            {
                "artifact_id": str(art_id),
                "kind": kind,
                "name": art.name,
                "preview": art.preview,
                "thread_id": str(thread_id) if thread_id else None,
                "job_id": str(job_id) if job_id else None,
            },
        )
        await db.commit()
    await push.emit(rt, ev)
    return art


async def save_text(
    rt: Runtime,
    user_id: uuid.UUID,
    thread_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
    title: str,
    text: str,
) -> Artifact:
    return await save(
        rt,
        user_id,
        text.encode(),
        name=f"{title}.txt",
        kind="text",
        mime="text/plain; charset=utf-8",
        thread_id=thread_id,
        job_id=job_id,
        preview={"text": text[:PREVIEW_CHARS]},
    )
