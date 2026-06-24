"""Add temporal shared policy assignment columns.

Revision ID: 20260616_0031
Revises: 20260616_0030
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0031"
down_revision: str | None = "20260616_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("policy_assignments"):
        return

    if not _has_column("policy_assignments", "policy_id"):
        op.add_column("policy_assignments", sa.Column("policy_id", sa.Uuid(), nullable=False))
        if op.get_bind().dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_policy_assignments_policy_id_policies",
                "policy_assignments",
                "policies",
                ["policy_id"],
                ["id"],
                ondelete="CASCADE",
            )
        op.create_index("ix_policy_assignments_policy_id", "policy_assignments", ["policy_id"])
    else:
        with op.batch_alter_table("policy_assignments") as batch_op:
            batch_op.alter_column("policy_id", existing_type=sa.Uuid(), nullable=False)

    if not _has_column("policy_assignments", "scope_target_key"):
        op.add_column(
            "policy_assignments",
            sa.Column("scope_target_key", sa.String(length=150), nullable=True),
        )
        op.create_index(
            "ix_policy_assignments_scope_target_key",
            "policy_assignments",
            ["scope_target_key"],
        )

    if not _has_column("policy_assignments", "mode"):
        op.add_column(
            "policy_assignments",
            sa.Column("mode", sa.String(length=50), nullable=False, server_default="enforce"),
        )
        op.alter_column("policy_assignments", "mode", server_default=None)

    if not _has_column("policy_assignments", "effective_from"):
        op.add_column(
            "policy_assignments",
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_policy_assignments_effective_from",
            "policy_assignments",
            ["effective_from"],
        )

    if not _has_column("policy_assignments", "effective_to"):
        op.add_column(
            "policy_assignments",
            sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column("policy_assignments", "superseded_by_assignment_id"):
        op.add_column(
            "policy_assignments",
            sa.Column("superseded_by_assignment_id", sa.Uuid(), nullable=True),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_policy_assignments_superseded_by_assignment_id",
                "policy_assignments",
                "policy_assignments",
                ["superseded_by_assignment_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index(
            "ix_policy_assignments_superseded_by_assignment_id",
            "policy_assignments",
            ["superseded_by_assignment_id"],
        )

    if not _has_index("policy_assignments", "uq_policy_assignments_open_shared_scope"):
        op.create_index(
            "uq_policy_assignments_open_shared_scope",
            "policy_assignments",
            ["policy_id", "scope_type", "scope_target_key"],
            unique=True,
            sqlite_where=sa.text("effective_to is null"),
            postgresql_where=sa.text("effective_to is null"),
        )


def downgrade() -> None:
    if not _has_table("policy_assignments"):
        return

    for index_name in (
        "uq_policy_assignments_open_shared_scope",
        "ix_policy_assignments_superseded_by_assignment_id",
        "ix_policy_assignments_effective_from",
        "ix_policy_assignments_scope_target_key",
        "ix_policy_assignments_policy_id",
    ):
        if _has_index("policy_assignments", index_name):
            op.drop_index(index_name, table_name="policy_assignments")

    for column_name in (
        "superseded_by_assignment_id",
        "effective_to",
        "effective_from",
        "mode",
        "scope_target_key",
        "policy_id",
    ):
        if _has_column("policy_assignments", column_name):
            op.drop_column("policy_assignments", column_name)


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
