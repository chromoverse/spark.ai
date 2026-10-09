"""App factory. Run: uv run uvicorn app.main:create_app --factory --port 8080"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import socketio
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, me
from app.core import errors
from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import setup_logging, trace_id_var
from app.core.runtime import Runtime


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    http: httpx.AsyncClient | None = None,
) -> socketio.ASGIApp:
    settings = settings or Settings()  # type: ignore[call-arg]  # required fields come from env
    setup_logging(settings.log_level)
    rt = Runtime.build(settings, clock or Clock(), http)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await rt.close()

    api = FastAPI(
        title="Spark Brain",
        version="2",
        lifespan=lifespan,
        docs_url="/docs" if settings.env == "dev" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.env == "dev" else None,
    )
    api.state.rt = rt
    errors.install(api)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Trace-Id"],
    )

    @api.middleware("http")
    async def trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("x-trace-id", "")[:64] or uuid.uuid4().hex
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    for router in (health.router, auth.router, me.router):
        api.include_router(router)
    return socketio.ASGIApp(rt.sio, other_asgi_app=api, socketio_path="socket.io")
