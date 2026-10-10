from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import Db, Me
from app.core.errors import NOT_FOUND, ApiError, ok
from app.db.models import Job, JobStep

router = APIRouter(prefix="/v2/jobs")


def _job(j: Job) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "title": j.title,
        "status": j.status,
        "todo": j.todo,
        "eta_s": j.eta_s,
        "summary": j.summary,
        "provider_used": j.provider_used,
        "usage": j.usage,
        "device_id": str(j.device_id) if j.device_id else None,
        "thread_id": str(j.thread_id) if j.thread_id else None,
        "created_at": j.created_at.isoformat(),
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


async def _owned(db: Db, me: Me, job_id: uuid.UUID) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.user_id == me.user_id))
    if job is None:
        raise ApiError("not_found", NOT_FOUND)
    return job


@router.get("")
async def list_jobs(me: Me, db: Db, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    """Newest first (Activity page, the Home job panel after a reconnect)."""
    rows = (
        await db.scalars(
            select(Job)
            .where(Job.user_id == me.user_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    ).all()
    return ok({"items": [_job(j) for j in rows], "next_cursor": None})


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, me: Me, db: Db) -> dict[str, Any]:
    job = await _owned(db, me, job_id)
    steps = (
        await db.scalars(
            select(JobStep)
            .where(JobStep.job_id == job.id, JobStep.user_id == me.user_id)
            .order_by(JobStep.started_at, JobStep.id)
        )
    ).all()
    return ok(
        _job(job)
        | {
            "steps": [
                {
                    "id": str(s.id),
                    "tool": s.tool,
                    "input": s.input,
                    "output": s.output,
                    "status": s.status,
                    "error": s.error,
                    "device_id": str(s.device_id) if s.device_id else None,
                    "started_at": s.started_at.isoformat(),
                    "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                }
                for s in steps
            ]
        }
    )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: uuid.UUID, me: Me, db: Db, request: Request) -> dict[str, Any]:
    """The Stop button: same as saying "stop" (§6.4). A finished job stays as it was."""
    job = await _owned(db, me, job_id)
    jobs = request.app.state.voice.jobs
    running = jobs.active.get(job.id)
    if running is not None:
        await jobs.cancel(running)
    return ok({"status": "cancelled" if running is not None else job.status})
