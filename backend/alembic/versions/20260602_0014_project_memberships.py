"""Add project memberships.

Revision ID: 20260602_0014
Revises: 20260602_0013
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260602_0014"
down_revision: str | Sequence[str] | None = "20260602_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if _has_table("project_memberships"):
        return
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_membership_user"),
    )
    for column_name in ("org_id", "project_id", "role", "user_id"):
        op.create_index(
            f"ix_project_memberships_{column_name}",
            "project_memberships",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("project_memberships")


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()
