"""Add guardrail assignment enforcement mode.

Revision ID: 20260529_0003
Revises: 20260529_0002
Create Date: 2026-05-29
"""

from collections.abc import Sequence

revision: str = "20260529_0003"
down_revision: str | None = "20260529_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
