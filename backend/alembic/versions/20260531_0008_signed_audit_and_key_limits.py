"""Add signed audit chain and virtual key limits.

Revision ID: 20260531_0008
Revises: 20260531_0007
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260531_0008"
down_revision: str | None = "20260531_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "audit_events",
        "previous_hash",
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "audit_events",
        "event_hash",
        sa.Column("event_hash", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "audit_events",
        "signature_algorithm",
        sa.Column(
            "signature_algorithm",
            sa.String(length=50),
            nullable=False,
            server_default="hmac-sha256",
        ),
    )
    _add_column_if_missing(
        "virtual_keys",
        "max_requests_per_minute",
        sa.Column("max_requests_per_minute", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "virtual_keys",
        "max_tokens_per_minute",
        sa.Column("max_tokens_per_minute", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "virtual_keys",
        "max_tokens_per_request",
        sa.Column("max_tokens_per_request", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    for table_name, column_name in (
        ("virtual_keys", "max_tokens_per_request"),
        ("virtual_keys", "max_tokens_per_minute"),
        ("virtual_keys", "max_requests_per_minute"),
        ("audit_events", "signature_algorithm"),
        ("audit_events", "event_hash"),
        ("audit_events", "previous_hash"),
    ):
        _drop_column_if_present(table_name, column_name)


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns(table_name)}
    if column_name in columns:
        return
    op.add_column(table_name, column)
    if column_name.endswith("_hash") or column_name.endswith("_minute"):
        op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name], unique=False)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns(table_name)}
    if column_name not in columns:
        return
    indexes = {item["name"] for item in inspect(bind).get_indexes(table_name)}
    index_name = f"ix_{table_name}_{column_name}"
    if index_name in indexes:
        op.drop_index(index_name, table_name=table_name)
    op.drop_column(table_name, column_name)
