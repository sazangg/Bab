"""Add project-scoped invite fields.

Revision ID: 20260607_0022
Revises: 20260607_0021
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260607_0022"
down_revision: str | Sequence[str] | None = "20260607_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("invites")}
    with op.batch_alter_table("invites") as batch:
        if "project_id" not in columns:
            batch.add_column(
                sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True)
            )
        if "project_role" not in columns:
            batch.add_column(sa.Column("project_role", sa.String(length=50), nullable=True))
    indexes = {item["name"] for item in inspect(bind).get_indexes("invites")}
    if "ix_invites_project_id" not in indexes:
        op.create_index("ix_invites_project_id", "invites", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in inspect(bind).get_indexes("invites")}
    if "ix_invites_project_id" in indexes:
        op.drop_index("ix_invites_project_id", table_name="invites")
    columns = {item["name"] for item in inspect(bind).get_columns("invites")}
    with op.batch_alter_table("invites") as batch:
        if "project_role" in columns:
            batch.drop_column("project_role")
        if "project_id" in columns:
            batch.drop_column("project_id")
