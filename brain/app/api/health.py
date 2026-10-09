from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.errors import ok
from app.core.runtime import Runtime

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return ok({"status": "up"})


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    rt: Runtime = request.app.state.rt

    async def db() -> None:
        async with rt.engine.connect() as conn:
            await conn.execute(text("select 1"))

    async def redis() -> None:
        await rt.redis.ping()

    checks: dict[str, str] = {}
    for name, probe in (("db", db), ("redis", redis)):
        try:
            async with asyncio.timeout(2):
                await probe()
            checks[name] = "up"
        except Exception:
            checks[name] = "down"
    up = all(v == "up" for v in checks.values())
    return JSONResponse(ok(checks), status_code=200 if up else 503)
