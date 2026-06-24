"""Add revision ownership for access policy public models.

Revision ID: 20260616_0032
Revises: 20260616_0031
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0032"
down_revision: str | None = "20260616_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("access_policy_public_models"):
        return

    columns = {column["name"]: column for column in _columns("access_policy_public_models")}
    foreign_keys = {foreign_key["name"] for foreign_key in _foreign_keys()}

    with op.batch_alter_table("access_policy_public_models") as batch_op:
        if columns["access_policy_id"]["nullable"] is False:
            batch_op.alter_column(
                "access_policy_id",
                existing_type=sa.Uuid(),
                nullable=True,
            )
        if "policy_revision_id" not in columns:
            batch_op.add_column(sa.Column("policy_revision_id", sa.Uuid(), nullable=False))
        else:
            batch_op.alter_column(
                "policy_revision_id",
                existing_type=sa.Uuid(),
                nullable=False,
            )
        if "fk_access_policy_public_models_policy_revision_id" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_access_policy_public_models_policy_revision_id",
                "policy_revisions",
                ["policy_revision_id"],
                ["id"],
                ondelete="CASCADE",
            )

    if not _has_index("ix_access_policy_public_models_policy_revision_id"):
        op.create_index(
            "ix_access_policy_public_models_policy_revision_id",
            "access_policy_public_models",
            ["policy_revision_id"],
        )
    if not _has_index("uq_access_policy_public_models_revision_name"):
        op.create_index(
            "uq_access_policy_public_models_revision_name",
            "access_policy_public_models",
            ["policy_revision_id", "public_model_name"],
            unique=True,
        )


def downgrade() -> None:
    if not _has_table("access_policy_public_models"):
        return

    for index_name in (
        "uq_access_policy_public_models_revision_name",
        "ix_access_policy_public_models_policy_revision_id",
    ):
        if _has_index(index_name):
            op.drop_index(index_name, table_name="access_policy_public_models")

    columns = {column["name"]: column for column in _columns("access_policy_public_models")}
    with op.batch_alter_table("access_policy_public_models") as batch_op:
        if "policy_revision_id" in columns:
            batch_op.drop_column("policy_revision_id")
        if columns["access_policy_id"]["nullable"] is True:
            batch_op.alter_column(
                "access_policy_id",
                existing_type=sa.Uuid(),
                nullable=False,
            )


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> list[dict]:
    return inspect(op.get_bind()).get_columns(table_name)


def _foreign_keys() -> list[dict]:
    return inspect(op.get_bind()).get_foreign_keys("access_policy_public_models")


def _has_index(index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in inspect(op.get_bind()).get_indexes("access_policy_public_models")
    )
