"""Remove legacy allocation schema.

Revision ID: 20260601_0011
Revises: 20260601_0010
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260601_0011"
down_revision: str | None = "20260601_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_limit_policy_reservations_if_missing()

    for table_name, column_names in (
        ("virtual_keys", ("allocation_id", "custom_allocation_id")),
        ("usage_records", ("allocation_id",)),
        ("activity_events", ("allocation_id",)),
        ("guardrail_assignments", ("allocation_id",)),
        ("guardrail_events", ("allocation_id",)),
    ):
        _drop_columns_if_present(table_name, column_names)

    _drop_columns_if_present(
        "virtual_keys",
        (
            "max_requests_per_minute",
            "max_tokens_per_minute",
            "max_tokens_per_request",
        ),
    )

    _drop_table_if_present("allocation_reservations")
    _drop_table_if_present("allocations")


def downgrade() -> None:
    pass


def _create_limit_policy_reservations_if_missing() -> None:
    if _has_table("limit_policy_reservations"):
        return
    op.create_table(
        "limit_policy_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("limit_policy_id", sa.Uuid(), nullable=True),
        sa.Column("virtual_key_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reserved_prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_completion_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_total_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_cents", sa.Integer(), nullable=True),
        sa.Column("actual_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_total_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_cents", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["limit_policy_id"], ["limit_policies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["virtual_key_id"], ["virtual_keys.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "created_at",
        "expires_at",
        "limit_policy_id",
        "org_id",
        "request_id",
        "status",
        "virtual_key_id",
    ):
        op.create_index(
            f"ix_limit_policy_reservations_{column_name}",
            "limit_policy_reservations",
            [column_name],
        )


def _drop_columns_if_present(table_name: str, column_names: tuple[str, ...]) -> None:
    if not _has_table(table_name):
        return
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    existing_columns = [column_name for column_name in column_names if column_name in columns]
    if not existing_columns:
        return
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    for column_name in existing_columns:
        index_name = f"ix_{table_name}_{column_name}"
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
    with op.batch_alter_table(table_name) as batch:
        for column_name in existing_columns:
            batch.drop_column(column_name)


def _drop_table_if_present(table_name: str) -> None:
    if _has_table(table_name):
        op.drop_table(table_name)


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()
