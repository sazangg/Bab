"""Add provider_model_offering_id to access route candidates.

Revision ID: 20260616_0033
Revises: 20260616_0032
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0033"
down_revision: str | None = "20260616_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("access_policy_route_candidates"):
        return

    columns = {column["name"] for column in _columns("access_policy_route_candidates")}
    foreign_keys = {foreign_key["name"] for foreign_key in _foreign_keys()}
    with op.batch_alter_table("access_policy_route_candidates") as batch_op:
        if "provider_model_offering_id" not in columns:
            batch_op.add_column(sa.Column("provider_model_offering_id", sa.Uuid(), nullable=True))
        if "fk_access_policy_route_candidates_provider_model_offering_id" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_access_policy_route_candidates_provider_model_offering_id",
                "provider_model_offerings",
                ["provider_model_offering_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    op.execute(
        sa.text(
            """
            UPDATE access_policy_route_candidates
            SET provider_model_offering_id = model_offering_id
            WHERE provider_model_offering_id IS NULL
            """
        )
    )

    if not _has_index("ix_access_policy_route_candidates_provider_model_offering_id"):
        op.create_index(
            "ix_access_policy_route_candidates_provider_model_offering_id",
            "access_policy_route_candidates",
            ["provider_model_offering_id"],
        )
    if not _has_index("uq_access_policy_route_candidates_provider_offering_route"):
        op.create_index(
            "uq_access_policy_route_candidates_provider_offering_route",
            "access_policy_route_candidates",
            [
                "public_model_id",
                "provider_id",
                "credential_pool_id",
                "provider_model_offering_id",
            ],
            unique=True,
        )


def downgrade() -> None:
    if not _has_table("access_policy_route_candidates"):
        return

    for index_name in (
        "uq_access_policy_route_candidates_provider_offering_route",
        "ix_access_policy_route_candidates_provider_model_offering_id",
    ):
        if _has_index(index_name):
            op.drop_index(index_name, table_name="access_policy_route_candidates")

    if "provider_model_offering_id" in {
        column["name"] for column in _columns("access_policy_route_candidates")
    }:
        with op.batch_alter_table("access_policy_route_candidates") as batch_op:
            batch_op.drop_column("provider_model_offering_id")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> list[dict]:
    return inspect(op.get_bind()).get_columns(table_name)


def _foreign_keys() -> list[dict]:
    return inspect(op.get_bind()).get_foreign_keys("access_policy_route_candidates")


def _has_index(index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in inspect(op.get_bind()).get_indexes("access_policy_route_candidates")
    )
