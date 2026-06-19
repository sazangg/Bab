"""Add shared policies and policy revisions.

Revision ID: 20260616_0030
Revises: 20260616_0029
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0030"
down_revision: str | None = "20260616_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("policies"):
        op.create_table(
            "policies",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "kind in ('access', 'limit', 'guardrail')",
                name="ck_policies_kind",
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in {
            "ix_policies_org_id": ["org_id"],
            "ix_policies_kind": ["kind"],
            "ix_policies_is_active": ["is_active"],
        }.items():
            op.create_index(name, "policies", columns)

    if not _has_table("policy_revisions"):
        op.create_table(
            "policy_revisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("policy_id", sa.Uuid(), nullable=False),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status in ('draft', 'active', 'archived')",
                name="ck_policy_revisions_status",
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["policy_id"], ["policies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("policy_id", "revision_number", name="uq_policy_revision_number"),
        )
        for name, columns in {
            "ix_policy_revisions_org_id": ["org_id"],
            "ix_policy_revisions_policy_id": ["policy_id"],
            "ix_policy_revisions_status": ["status"],
        }.items():
            op.create_index(name, "policy_revisions", columns)
        op.create_index(
            "uq_policy_revisions_active",
            "policy_revisions",
            ["policy_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    for table_name in ("policy_revisions", "policies"):
        if _has_table(table_name):
            op.drop_table(table_name)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)
