"""Add guardrail assignment enforcement mode.

Revision ID: 20260529_0003
Revises: 20260529_0002
Create Date: 2026-05-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260529_0003"
down_revision: str | None = "20260529_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("guardrail_assignments")}
    if "enforcement_mode" not in columns:
        op.add_column(
            "guardrail_assignments",
            sa.Column(
                "enforcement_mode",
                sa.String(length=50),
                nullable=False,
                server_default="enforce",
            ),
        )
        op.create_index(
            "ix_guardrail_assignments_enforcement_mode",
            "guardrail_assignments",
            ["enforcement_mode"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("guardrail_assignments")}
    if "enforcement_mode" in columns:
        op.drop_index(
            "ix_guardrail_assignments_enforcement_mode",
            table_name="guardrail_assignments",
        )
        op.drop_column("guardrail_assignments", "enforcement_mode")
