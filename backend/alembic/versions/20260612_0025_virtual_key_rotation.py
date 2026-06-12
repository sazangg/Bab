"""Add virtual key rotation lifecycle fields.

Revision ID: 20260612_0025
Revises: 20260609_0024
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op

revision: str = "20260612_0025"
down_revision: str | None = "20260609_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("virtual_keys")}
    if "supersedes_key_id" not in columns:
        op.add_column("virtual_keys", sa.Column("supersedes_key_id", sa.Uuid(), nullable=True))
    if "deprecated_at" not in columns:
        op.add_column(
            "virtual_keys",
            sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        )

    inspector = inspect(bind)
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("virtual_keys")}
    if "fk_virtual_keys_supersedes_key_id_virtual_keys" not in foreign_keys:
        with op.batch_alter_table("virtual_keys") as batch_op:
            batch_op.create_foreign_key(
                "fk_virtual_keys_supersedes_key_id_virtual_keys",
                "virtual_keys",
                ["supersedes_key_id"],
                ["id"],
                ondelete="SET NULL",
            )

    inspector = inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("virtual_keys")}
    if "ix_virtual_keys_supersedes_key_id" not in indexes:
        op.create_index(
            "ix_virtual_keys_supersedes_key_id",
            "virtual_keys",
            ["supersedes_key_id"],
        )
    if "ix_virtual_keys_deprecated_at" not in indexes:
        op.create_index("ix_virtual_keys_deprecated_at", "virtual_keys", ["deprecated_at"])


def downgrade() -> None:
    op.drop_index("ix_virtual_keys_deprecated_at", table_name="virtual_keys")
    op.drop_index("ix_virtual_keys_supersedes_key_id", table_name="virtual_keys")
    with op.batch_alter_table("virtual_keys") as batch_op:
        batch_op.drop_constraint(
            "fk_virtual_keys_supersedes_key_id_virtual_keys",
            type_="foreignkey",
        )
        batch_op.drop_column("deprecated_at")
        batch_op.drop_column("supersedes_key_id")
