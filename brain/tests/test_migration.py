from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection

from app.db.base import Base, uuid7
from tests.conftest import Brain


async def test_models_match_migration(brain: Brain) -> None:
    def diff(conn: Connection) -> list[object]:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)

    async with brain.rt.engine.connect() as conn:
        assert await conn.run_sync(diff) == []


def test_uuid7_is_versioned_and_time_ordered() -> None:
    ids = [uuid7() for _ in range(50)]
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert [u.int >> 80 for u in ids] == sorted(u.int >> 80 for u in ids)
