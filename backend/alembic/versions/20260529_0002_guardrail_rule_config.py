"""add guardrail rule config for pre-alembic databases

Revision ID: 20260529_0002
Revises: 20260529_0001
Create Date: 2026-05-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260529_0002"
down_revision: str | None = "20260529_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("guardrail_rules")}
    if "config" not in columns:
        op.add_column(
            "guardrail_rules",
            sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("guardrail_rules")}
    if "config" in columns:
        op.drop_column("guardrail_rules", "config")
