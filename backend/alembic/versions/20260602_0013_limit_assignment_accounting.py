"""Add assignment-scoped limit accounting.

Revision ID: 20260602_0013
Revises: 20260601_0012
Create Date: 2026-06-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260602_0013"
down_revision: str | Sequence[str] | None = "20260601_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "usage_records",
        sa.Column("limit_policy_assignment_ids", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "limit_policy_reservations",
        sa.Column("limit_policy_assignment_id", sa.Uuid(), nullable=False),
    )
    if _has_table("limit_policy_reservations"):
        indexes = {
            index["name"]
            for index in inspect(op.get_bind()).get_indexes("limit_policy_reservations")
        }
        if "ix_limit_policy_reservations_limit_policy_assignment_id" not in indexes:
            op.create_index(
                "ix_limit_policy_reservations_limit_policy_assignment_id",
                "limit_policy_reservations",
                ["limit_policy_assignment_id"],
            )
        foreign_keys = {
            foreign_key["name"]
            for foreign_key in inspect(op.get_bind()).get_foreign_keys(
                "limit_policy_reservations"
            )
        }
        if (
            op.get_bind().dialect.name != "sqlite"
            and "fk_limit_policy_reservations_assignment_id" not in foreign_keys
        ):
            op.create_foreign_key(
                "fk_limit_policy_reservations_assignment_id",
                "limit_policy_reservations",
                "policy_assignments",
                ["limit_policy_assignment_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_limit_policy_reservations_assignment_id",
        "limit_policy_reservations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_limit_policy_reservations_limit_policy_assignment_id",
        table_name="limit_policy_reservations",
    )
    op.drop_column("limit_policy_reservations", "limit_policy_assignment_id")
    op.drop_column("usage_records", "limit_policy_assignment_ids")


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_table(table_name):
        return
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()
