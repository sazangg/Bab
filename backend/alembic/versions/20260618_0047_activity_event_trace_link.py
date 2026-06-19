"""add activity event gateway request link

Revision ID: 20260618_0047
Revises: 20260618_0046
Create Date: 2026-06-18 00:47:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0047"
down_revision: str | None = "20260618_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("activity_events"):
        return
    if not _has_column("activity_events", "gateway_request_id"):
        op.add_column("activity_events", sa.Column("gateway_request_id", sa.Uuid(), nullable=True))
    if not _has_index("activity_events", "ix_activity_events_gateway_request_id"):
        op.create_index(
            "ix_activity_events_gateway_request_id",
            "activity_events",
            ["gateway_request_id"],
        )


def downgrade() -> None:
    if not _has_table("activity_events"):
        return
    if _has_index("activity_events", "ix_activity_events_gateway_request_id"):
        op.drop_index("ix_activity_events_gateway_request_id", table_name="activity_events")
    if _has_column("activity_events", "gateway_request_id"):
        op.drop_column("activity_events", "gateway_request_id")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )
