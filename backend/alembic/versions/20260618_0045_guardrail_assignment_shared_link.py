"""Link guardrail assignments to shared policy assignments.

Revision ID: 20260618_0045
Revises: 20260618_0044
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0045"
down_revision: str | None = "20260618_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("guardrail_assignments"):
        return
    with op.batch_alter_table("guardrail_assignments") as batch_op:
        if not _has_column("guardrail_assignments", "policy_assignment_id"):
            batch_op.add_column(sa.Column("policy_assignment_id", sa.Uuid(), nullable=True))
        if not _has_fk(
            "guardrail_assignments",
            "fk_guardrail_assignments_policy_assignment_id_policy_assignments",
        ):
            batch_op.create_foreign_key(
                "fk_guardrail_assignments_policy_assignment_id_policy_assignments",
                "policy_assignments",
                ["policy_assignment_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if not _has_index("guardrail_assignments", "ix_guardrail_assignments_policy_assignment_id"):
        op.create_index(
            "ix_guardrail_assignments_policy_assignment_id",
            "guardrail_assignments",
            ["policy_assignment_id"],
        )


def downgrade() -> None:
    if not _has_table("guardrail_assignments"):
        return
    if _has_index("guardrail_assignments", "ix_guardrail_assignments_policy_assignment_id"):
        op.drop_index(
            "ix_guardrail_assignments_policy_assignment_id",
            table_name="guardrail_assignments",
        )
    with op.batch_alter_table("guardrail_assignments") as batch_op:
        if _has_column("guardrail_assignments", "policy_assignment_id"):
            batch_op.drop_column("policy_assignment_id")


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


def _has_fk(table_name: str, constraint_name: str) -> bool:
    return any(
        fk["name"] == constraint_name for fk in inspect(op.get_bind()).get_foreign_keys(table_name)
    )
