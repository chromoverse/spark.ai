"""r1 incidents

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("engine_or_provider", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("remedy", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("signal_id", sa.String(), nullable=True),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_incidents_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_incidents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents_user_id_ts"), "incidents", ["user_id", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_incidents_user_id_ts"), table_name="incidents")
    op.drop_table("incidents")
