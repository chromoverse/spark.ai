"""Shared harness (TESTING.md §2). DB-backed tests need the test stack:
docker compose -f deploy/docker-compose.test.yml up -d
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import socketio
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.runtime import Runtime
from app.db import models  # noqa: F401  (registers tables for TRUNCATE)
from app.db.base import Base
from app.main import create_app
from tests.fakes.clock import FakeClock

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://spark:spark@127.0.0.1:55432/spark_test"
)
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/0")


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": TEST_DB,
        "redis_url": TEST_REDIS,
        "jwt_secret": "test-secret-" + "x" * 40,
        "public_url": "http://localhost:8080",
        "google_client_id": "test-client.apps.googleusercontent.com",
        "google_client_secret": "test-google-secret",
        "resend_api_key": "re_test",
        "log_level": "WARNING",
    } | overrides
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


Handler = Callable[[httpx.Request], Any]


class FakeHttp:
    """Routes the brain's shared httpx client to fakes by host. Unknown hosts fail loudly:
    no real network in tests (TESTING.md §1.2)."""

    def __init__(self) -> None:
        self.hosts: dict[str, Handler] = {}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        handler = self.hosts.get(request.url.host)
        if handler is None:
            raise AssertionError(f"unexpected outbound call to {request.url}")
        result = handler(request)
        return await result if asyncio.iscoroutine(result) else result


@dataclass
class Brain:
    url: str
    asgi: socketio.ASGIApp
    rt: Runtime
    clock: FakeClock
    fake_http: FakeHttp
    client: httpx.AsyncClient


BRAIN_DIR = Path(__file__).resolve().parents[1]


async def _migrate_fresh_schema() -> None:
    """Every run proves the real migration: drop everything, then `alembic upgrade head`."""
    engine = create_async_engine(TEST_DB, connect_args={"timeout": 5})
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    except OSError as exc:
        pytest.fail(
            f"test stack not reachable ({exc}); run "
            "`docker compose -f deploy/docker-compose.test.yml up -d`"
        )
    finally:
        await engine.dispose()
    cfg = Config(str(BRAIN_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest.fixture(scope="session")
async def brain_server() -> AsyncIterator[Brain]:
    await _migrate_fresh_schema()
    clock = FakeClock()
    fake_http = FakeHttp()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake_http.handle))
    asgi = create_app(make_settings(), clock=clock, http=http)
    server = uvicorn.Server(
        uvicorn.Config(asgi, host="127.0.0.1", port=0, lifespan="on", log_config=None)
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=url, timeout=10) as client:
        yield Brain(url, asgi, asgi.other_asgi_app.state.rt, clock, fake_http, client)
    server.should_exit = True
    await task


_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)


@pytest.fixture
async def brain(brain_server: Brain) -> AsyncIterator[Brain]:
    """The shared server with empty tables, empty Redis, and fresh fakes."""
    async with brain_server.rt.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    await brain_server.rt.redis.flushdb()
    brain_server.fake_http.hosts.clear()
    yield brain_server
