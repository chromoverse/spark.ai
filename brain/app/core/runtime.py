from __future__ import annotations

from dataclasses import dataclass

import httpx
import socketio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.clock import Clock
from app.core.config import Settings
from app.llm.chains import ChainRunner
from app.memory.embed import Embedder


@dataclass
class Runtime:
    """Process-wide handles. Built once in create_app; tests inject the clock and http client."""

    settings: Settings
    clock: Clock
    http: httpx.AsyncClient
    engine: AsyncEngine
    db: async_sessionmaker[AsyncSession]
    redis: Redis
    sio: socketio.AsyncServer
    llm: ChainRunner
    embedder: Embedder

    @classmethod
    def build(
        cls,
        settings: Settings,
        clock: Clock,
        http: httpx.AsyncClient | None,
        embedder: Embedder | None = None,
    ) -> Runtime:
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={
                "timeout": 5,
                "command_timeout": 10,
                # memories of many users share one HNSW index: keep scanning until this user's
                # rows fill the LIMIT (pgvector ≥ 0.8), in exact distance order
                "server_settings": {
                    "hnsw.iterative_scan": "strict_order",
                    "plan_cache_mode": "force_custom_plan",
                },
            },
        )
        sio = socketio.AsyncServer(
            async_mode="asgi",
            # Redis manager so emits reach sockets held by any brain process.
            client_manager=socketio.AsyncRedisManager(settings.redis_url),
            cors_allowed_origins=settings.cors_origin_list,
            logger=False,
            engineio_logger=False,
        )
        http = http or httpx.AsyncClient(http2=True, timeout=httpx.Timeout(10, connect=5))
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        return cls(
            settings=settings,
            clock=clock,
            http=http,
            engine=engine,
            db=async_sessionmaker(engine, expire_on_commit=False),
            redis=redis,
            sio=sio,
            llm=ChainRunner(settings, clock, http, redis),
            embedder=embedder or Embedder(settings.models_dir),
        )

    async def close(self) -> None:
        await self.llm.aclose()
        await self.http.aclose()
        await self.redis.aclose()
        await self.engine.dispose()
