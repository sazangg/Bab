"""Link legacy access policies to shared policy identity.

Revision ID: 20260617_0034
Revises: 20260616_0033
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260617_0034"
down_revision: str | None = "20260616_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("access_policies"):
        return

    columns = {column["name"] for column in _columns()}
    foreign_keys = {foreign_key["name"] for foreign_key in _foreign_keys()}
    with op.batch_alter_table("access_policies") as batch_op:
        if "policy_id" not in columns:
            batch_op.add_column(sa.Column("policy_id", sa.Uuid(), nullable=True))
        if "fk_access_policies_policy_id_policies" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_access_policies_policy_id_policies",
                "policies",
                ["policy_id"],
                ["id"],
                ondelete="CASCADE",
            )

    if not _has_index("ix_access_policies_policy_id"):
        op.create_index("ix_access_policies_policy_id", "access_policies", ["policy_id"])
    if not _has_index("uq_access_policies_policy_id"):
        op.create_index(
            "uq_access_policies_policy_id",
            "access_policies",
            ["policy_id"],
            unique=True,
        )


def downgrade() -> None:
    if not _has_table("access_policies"):
        return

    for index_name in ("uq_access_policies_policy_id", "ix_access_policies_policy_id"):
        if _has_index(index_name):
            op.drop_index(index_name, table_name="access_policies")
    if "policy_id" in {column["name"] for column in _columns()}:
        with op.batch_alter_table("access_policies") as batch_op:
            batch_op.drop_column("policy_id")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _columns() -> list[dict]:
    return inspect(op.get_bind()).get_columns("access_policies")


def _foreign_keys() -> list[dict]:
    return inspect(op.get_bind()).get_foreign_keys("access_policies")


def _has_index(index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in inspect(op.get_bind()).get_indexes("access_policies")
    )
