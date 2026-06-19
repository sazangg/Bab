"""Link guardrail events to gateway traces.

Revision ID: 20260618_0036
Revises: 20260617_0035
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0036"
down_revision: str | None = "20260617_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("guardrail_events"):
        return
    with op.batch_alter_table("guardrail_events") as batch_op:
        if not _has_column("guardrail_events", "gateway_request_id"):
            batch_op.add_column(sa.Column("gateway_request_id", sa.Uuid(), nullable=True))
        if not _has_column("guardrail_events", "route_attempt_id"):
            batch_op.add_column(sa.Column("route_attempt_id", sa.Uuid(), nullable=True))
    if not _has_index("guardrail_events", "ix_guardrail_events_gateway_request_id"):
        op.create_index(
            "ix_guardrail_events_gateway_request_id",
            "guardrail_events",
            ["gateway_request_id"],
        )
    if not _has_index("guardrail_events", "ix_guardrail_events_route_attempt_id"):
        op.create_index(
            "ix_guardrail_events_route_attempt_id",
            "guardrail_events",
            ["route_attempt_id"],
        )


def downgrade() -> None:
    if not _has_table("guardrail_events"):
        return
    for index_name in (
        "ix_guardrail_events_route_attempt_id",
        "ix_guardrail_events_gateway_request_id",
    ):
        if _has_index("guardrail_events", index_name):
            op.drop_index(index_name, table_name="guardrail_events")
    with op.batch_alter_table("guardrail_events") as batch_op:
        if _has_column("guardrail_events", "route_attempt_id"):
            batch_op.drop_column("route_attempt_id")
        if _has_column("guardrail_events", "gateway_request_id"):
            batch_op.drop_column("gateway_request_id")


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
