"""Link guardrail assignments to shared policy assignments.

Revision ID: 20260618_0045
Revises: 20260618_0044
Create Date: 2026-06-18
"""

from collections.abc import Sequence

revision: str = "20260618_0045"
down_revision: str | None = "20260618_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
