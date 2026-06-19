"""Add guardrail policy revision content links.

Revision ID: 20260618_0043
Revises: 20260618_0042
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0043"
down_revision: str | None = "20260618_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("guardrail_policies") or not _has_table("guardrail_rules"):
        return
    with op.batch_alter_table("guardrail_policies") as batch_op:
        if not _has_column("guardrail_policies", "policy_id"):
            batch_op.add_column(sa.Column("policy_id", sa.Uuid(), nullable=True))
        if not _has_fk("guardrail_policies", "fk_guardrail_policies_policy_id_policies"):
            batch_op.create_foreign_key(
                "fk_guardrail_policies_policy_id_policies",
                "policies",
                ["policy_id"],
                ["id"],
                ondelete="CASCADE",
            )
    with op.batch_alter_table("guardrail_rules") as batch_op:
        if not _has_column("guardrail_rules", "policy_revision_id"):
            batch_op.add_column(sa.Column("policy_revision_id", sa.Uuid(), nullable=True))
        if not _has_fk(
            "guardrail_rules",
            "fk_guardrail_rules_policy_revision_id_policy_revisions",
        ):
            batch_op.create_foreign_key(
                "fk_guardrail_rules_policy_revision_id_policy_revisions",
                "policy_revisions",
                ["policy_revision_id"],
                ["id"],
                ondelete="CASCADE",
            )

    _create_index(
        "ix_guardrail_policies_policy_id",
        "guardrail_policies",
        ["policy_id"],
        unique=True,
    )
    _create_index(
        "ix_guardrail_rules_policy_revision_id",
        "guardrail_rules",
        ["policy_revision_id"],
    )


def downgrade() -> None:
    if not _has_table("guardrail_policies") or not _has_table("guardrail_rules"):
        return
    if _has_index("guardrail_rules", "ix_guardrail_rules_policy_revision_id"):
        op.drop_index("ix_guardrail_rules_policy_revision_id", table_name="guardrail_rules")
    if _has_index("guardrail_policies", "ix_guardrail_policies_policy_id"):
        op.drop_index("ix_guardrail_policies_policy_id", table_name="guardrail_policies")
    with op.batch_alter_table("guardrail_rules") as batch_op:
        if _has_column("guardrail_rules", "policy_revision_id"):
            batch_op.drop_column("policy_revision_id")
    with op.batch_alter_table("guardrail_policies") as batch_op:
        if _has_column("guardrail_policies", "policy_id"):
            batch_op.drop_column("policy_id")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in inspect(op.get_bind()).get_columns(table_name)
    }


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )


def _has_fk(table_name: str, constraint_name: str) -> bool:
    return any(
        fk["name"] == constraint_name for fk in inspect(op.get_bind()).get_foreign_keys(table_name)
    )
