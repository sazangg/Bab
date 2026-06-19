"""Add limit policy rule matcher and partition tables.

Revision ID: 20260618_0037
Revises: 20260618_0036
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0037"
down_revision: str | None = "20260618_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("limit_policy_rule_matchers"):
        op.create_table(
            "limit_policy_rule_matchers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("rule_id", sa.Uuid(), nullable=False),
            sa.Column("dimension", sa.String(length=100), nullable=False),
            sa.Column("operator", sa.String(length=50), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["rule_id"], ["limit_policy_rules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_table("limit_policy_rule_partitions"):
        op.create_table(
            "limit_policy_rule_partitions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("rule_id", sa.Uuid(), nullable=False),
            sa.Column("dimension", sa.String(length=100), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["rule_id"], ["limit_policy_rules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "rule_id",
                "position",
                name="uq_limit_rule_partitions_rule_position",
            ),
            sa.UniqueConstraint(
                "rule_id",
                "dimension",
                name="uq_limit_rule_partitions_rule_dimension",
            ),
        )
    _create_index(
        "ix_limit_policy_rule_matchers_org_id",
        "limit_policy_rule_matchers",
        ["org_id"],
    )
    _create_index(
        "ix_limit_policy_rule_matchers_rule_id",
        "limit_policy_rule_matchers",
        ["rule_id"],
    )
    _create_index(
        "ix_limit_policy_rule_matchers_dimension",
        "limit_policy_rule_matchers",
        ["dimension"],
    )
    _create_index(
        "ix_limit_rule_matchers_rule_position",
        "limit_policy_rule_matchers",
        ["rule_id", "created_at", "id"],
    )
    _create_index(
        "ix_limit_policy_rule_partitions_org_id",
        "limit_policy_rule_partitions",
        ["org_id"],
    )
    _create_index(
        "ix_limit_policy_rule_partitions_rule_id",
        "limit_policy_rule_partitions",
        ["rule_id"],
    )
    _create_index(
        "ix_limit_policy_rule_partitions_dimension",
        "limit_policy_rule_partitions",
        ["dimension"],
    )


def downgrade() -> None:
    for table_name, index_name in (
        ("limit_policy_rule_partitions", "ix_limit_policy_rule_partitions_dimension"),
        ("limit_policy_rule_partitions", "ix_limit_policy_rule_partitions_rule_id"),
        ("limit_policy_rule_partitions", "ix_limit_policy_rule_partitions_org_id"),
        ("limit_policy_rule_matchers", "ix_limit_rule_matchers_rule_position"),
        ("limit_policy_rule_matchers", "ix_limit_policy_rule_matchers_dimension"),
        ("limit_policy_rule_matchers", "ix_limit_policy_rule_matchers_rule_id"),
        ("limit_policy_rule_matchers", "ix_limit_policy_rule_matchers_org_id"),
    ):
        if _has_table(table_name) and _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
    if _has_table("limit_policy_rule_partitions"):
        op.drop_table("limit_policy_rule_partitions")
    if _has_table("limit_policy_rule_matchers"):
        op.drop_table("limit_policy_rule_matchers")


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )
