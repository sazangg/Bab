"""Add request correlation ids to gateway records.

Revision ID: 20260531_0004
Revises: 20260529_0003
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260531_0004"
down_revision: str | None = "20260529_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_request_id("usage_records")
    _add_request_id("activity_events")
    _add_request_id("guardrail_events")


def downgrade() -> None:
    _drop_request_id("guardrail_events")
    _drop_request_id("activity_events")
    _drop_request_id("usage_records")


def _add_request_id(table_name: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns(table_name)}
    if "request_id" in columns:
        return
    op.add_column(table_name, sa.Column("request_id", sa.String(length=100), nullable=True))
    op.create_index(f"ix_{table_name}_request_id", table_name, ["request_id"], unique=False)


def _drop_request_id(table_name: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns(table_name)}
    if "request_id" not in columns:
        return
    op.drop_index(f"ix_{table_name}_request_id", table_name=table_name)
    op.drop_column(table_name, "request_id")
