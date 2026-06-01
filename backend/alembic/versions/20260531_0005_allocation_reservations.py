"""Add allocation reservation ledger.

Revision ID: 20260531_0005
Revises: 20260531_0004
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260531_0005"
down_revision: str | None = "20260531_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = set(inspect(bind).get_table_names())
    if "allocation_reservations" in table_names or "allocations" not in table_names:
        return
    op.create_table(
        "allocation_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("allocation_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["allocation_id"], ["allocations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["virtual_key_id"], ["virtual_keys.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "allocation_id",
        "created_at",
        "expires_at",
        "org_id",
        "request_id",
        "status",
        "virtual_key_id",
    ):
        op.create_index(
            f"ix_allocation_reservations_{column_name}",
            "allocation_reservations",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "allocation_reservations" not in inspect(bind).get_table_names():
        return
    op.drop_table("allocation_reservations")
