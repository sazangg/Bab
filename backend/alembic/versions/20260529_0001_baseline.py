"""baseline current schema

Revision ID: 20260529_0001
Revises:
Create Date: 2026-05-29
"""

from collections.abc import Sequence

from alembic import op
from app.core.database import Base
from app.core.model_imports import import_all_models

revision: str = "20260529_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    import_all_models()
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    import_all_models()
    Base.metadata.drop_all(bind=op.get_bind())
