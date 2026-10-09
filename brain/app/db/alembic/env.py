from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests pass the URL in; everything else reads DATABASE_URL via Settings.
    url = context.config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from app.core.config import Settings

    return Settings().database_url  # type: ignore[call-arg]


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), connect_args={"timeout": 10})
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async())
