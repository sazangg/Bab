"""Constrain guardrail event decisions.

Revision ID: 20260618_0046
Revises: 20260618_0045
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0046"
down_revision: str | None = "20260618_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ck_guardrail_events_decision"
ALLOWED_DECISIONS = "'allowed', 'blocked', 'would_allow', 'would_block'"


def upgrade() -> None:
    if not _has_table("guardrail_events"):
        return
    op.execute(
        sa.text("update guardrail_events set decision = 'would_block' where decision = 'dry_run'")
    )
    if _has_check("guardrail_events", CONSTRAINT_NAME):
        return
    with op.batch_alter_table("guardrail_events") as batch_op:
        batch_op.create_check_constraint(
            CONSTRAINT_NAME,
            f"decision in ({ALLOWED_DECISIONS})",
        )


def downgrade() -> None:
    if not _has_table("guardrail_events") or not _has_check(
        "guardrail_events",
        CONSTRAINT_NAME,
    ):
        return
    with op.batch_alter_table("guardrail_events") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_check(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in inspect(op.get_bind()).get_check_constraints(table_name)
    )
