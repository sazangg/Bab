"""remove virtual key allowed models

Revision ID: 20260602_0015
Revises: 20260602_0014
Create Date: 2026-06-02 14:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_0015"
down_revision: str | None = "20260602_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("virtual_keys")}
    if "allowed_models" in columns:
        op.drop_column("virtual_keys", "allowed_models")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("virtual_keys")}
    if "allowed_models" not in columns:
        op.add_column("virtual_keys", sa.Column("allowed_models", sa.JSON(), nullable=True))
