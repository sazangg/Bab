"""Add guardrail rule matcher table.

Revision ID: 20260618_0042
Revises: 20260618_0041
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0042"
down_revision: str | None = "20260618_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("guardrail_rule_matchers"):
        op.create_table(
            "guardrail_rule_matchers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("rule_id", sa.Uuid(), nullable=False),
            sa.Column("dimension", sa.String(length=100), nullable=False),
            sa.Column("operator", sa.String(length=50), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["rule_id"], ["guardrail_rules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_guardrail_rule_matchers_org_id", "guardrail_rule_matchers", ["org_id"])
    _create_index("ix_guardrail_rule_matchers_rule_id", "guardrail_rule_matchers", ["rule_id"])
    _create_index(
        "ix_guardrail_rule_matchers_dimension",
        "guardrail_rule_matchers",
        ["dimension"],
    )


def downgrade() -> None:
    if not _has_table("guardrail_rule_matchers"):
        return
    for index_name in (
        "ix_guardrail_rule_matchers_dimension",
        "ix_guardrail_rule_matchers_rule_id",
        "ix_guardrail_rule_matchers_org_id",
    ):
        if _has_index("guardrail_rule_matchers", index_name):
            op.drop_index(index_name, table_name="guardrail_rule_matchers")
    op.drop_table("guardrail_rule_matchers")


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )
