"""Add provider pricing catalog fields.

Revision ID: 20260531_0006
Revises: 20260531_0005
Create Date: 2026-05-31
"""

from collections.abc import Sequence

revision: str = "20260531_0006"
down_revision: str | None = "20260531_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
