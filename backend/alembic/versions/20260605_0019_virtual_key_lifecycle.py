"""Add virtual key lifecycle metadata.

Revision ID: 20260605_0019
Revises: 20260605_0018
Create Date: 2026-06-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260605_0019"
down_revision: str | Sequence[str] | None = "20260605_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("virtual_keys")}
    with op.batch_alter_table("virtual_keys") as batch:
        if "created_by" not in columns:
            batch.add_column(sa.Column("created_by", sa.Uuid(), nullable=True))
        if "last_used_at" not in columns:
            batch.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        if "revoked_by" not in columns:
            batch.add_column(sa.Column("revoked_by", sa.Uuid(), nullable=True))
        if "revoked_reason" not in columns:
            batch.add_column(sa.Column("revoked_reason", sa.String(500), nullable=True))

    indexes = {item["name"] for item in inspect(bind).get_indexes("virtual_keys")}
    for index_name, columns in (
        ("ix_virtual_keys_created_by", ["created_by"]),
        ("ix_virtual_keys_last_used_at", ["last_used_at"]),
        ("ix_virtual_keys_project_revoked", ["project_id", "revoked_at"]),
    ):
        if index_name not in indexes:
            op.create_index(index_name, "virtual_keys", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in inspect(bind).get_indexes("virtual_keys")}
    for index_name in (
        "ix_virtual_keys_project_revoked",
        "ix_virtual_keys_last_used_at",
        "ix_virtual_keys_created_by",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="virtual_keys")

    columns = {item["name"] for item in inspect(bind).get_columns("virtual_keys")}
    with op.batch_alter_table("virtual_keys") as batch:
        for column_name in ("revoked_reason", "revoked_by", "last_used_at", "created_by"):
            if column_name in columns:
                batch.drop_column(column_name)
