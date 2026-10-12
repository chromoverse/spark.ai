"""App factory. Run: uv run uvicorn app.main:create_app --factory --port 8080"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import socketio
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    artifacts,
    auth,
    capabilities,
    devices,
    engines,
    health,
    incidents,
    jobs,
    me,
    memories,
    permissions,
    proxy,
    threads,
)
from app.core import errors
from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import setup_logging, trace_id_var
from app.core.runtime import Runtime
from app.gateway import server as gateway
from app.memory import store
from app.memory.embed import Embedder


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    http: httpx.AsyncClient | None = None,
    embedder: Embedder | None = None,
) -> socketio.ASGIApp:
    settings = settings or Settings()  # required fields come from env
    setup_logging(settings.log_level)
    rt = Runtime.build(settings, clock or Clock(), http, embedder)
    voice = gateway.register(rt)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await voice.jobs.fail_stale()

        async def embedder_up() -> None:  # first start downloads ~135 MB
            await rt.embedder.start(rt.http)
            await store.embed_missing(rt)

        voice._spawn(embedder_up())
        supervisor = asyncio.create_task(voice.sup.run())
        yield
        supervisor.cancel()
        for task in (supervisor, *voice.tasks):
            task.cancel()
        await asyncio.gather(supervisor, *voice.tasks, return_exceptions=True)
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
    api.state.voice = voice
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

    for router in (
        health.router,
        auth.router,
        me.router,
        devices.router,
        incidents.router,
        proxy.router,
        jobs.router,
        permissions.router,
        capabilities.router,
        artifacts.router,
        threads.router,
        engines.router,
        memories.router,
    ):
        api.include_router(router)
    return socketio.ASGIApp(rt.sio, other_asgi_app=api, socketio_path="socket.io")
