"""Add audit ledger state rows.

Revision ID: 20260609_0023
Revises: 20260607_0022
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260609_0023"
down_revision: str | None = "20260607_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = inspect(bind).get_table_names()
    if "audit_ledger_states" in tables:
        return
    op.create_table(
        "audit_ledger_states",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("latest_event_hash", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "audit_ledger_states" in inspect(bind).get_table_names():
        op.drop_table("audit_ledger_states")
