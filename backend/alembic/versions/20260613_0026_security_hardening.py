"""Security/correctness hardening: single-org constraint, audit key id, cost precision.

Revision ID: 20260613_0026
Revises: 20260612_0025
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260613_0026"
down_revision: str | None = "20260612_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Per-event audit signing key id (decouples audit HMAC from the JWT secret).
    if "signing_key_id" not in _columns(inspector, "audit_events"):
        op.add_column(
            "audit_events", sa.Column("signing_key_id", sa.String(length=32), nullable=True)
        )

    # Exact micro-cent cost accounting for budget enforcement.
    if "cost_micro_cents" not in _columns(inspector, "usage_records"):
        op.add_column(
            "usage_records", sa.Column("cost_micro_cents", sa.BigInteger(), nullable=True)
        )

    reservation_columns = _columns(inspector, "limit_policy_reservations")
    if "reserved_cost_micro_cents" not in reservation_columns:
        op.add_column(
            "limit_policy_reservations",
            sa.Column("reserved_cost_micro_cents", sa.BigInteger(), nullable=True),
        )
    if "actual_cost_micro_cents" not in reservation_columns:
        op.add_column(
            "limit_policy_reservations",
            sa.Column("actual_cost_micro_cents", sa.BigInteger(), nullable=True),
        )

    # One account belongs to exactly one organization. A unique index enforces it on
    # existing databases (the baseline create_all renders the model's UniqueConstraint).
    # This raises if pre-existing data already has a user in multiple orgs; those rows
    # must be resolved before upgrading.
    inspector = inspect(bind)
    if "uq_org_membership_single_org" not in _indexes(inspector, "organization_memberships"):
        op.create_index(
            "uq_org_membership_single_org",
            "organization_memberships",
            ["user_id"],
            unique=True,
        )

    # Shared policy assignment uniqueness is owned by the canonical policy_id index
    # added in the policy assignment temporal migration.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS uq_active_policy_assignment"))
    if "uq_org_membership_single_org" in _indexes(inspector, "organization_memberships"):
        op.drop_index("uq_org_membership_single_org", table_name="organization_memberships")
    with op.batch_alter_table("limit_policy_reservations") as batch_op:
        batch_op.drop_column("actual_cost_micro_cents")
        batch_op.drop_column("reserved_cost_micro_cents")
    op.drop_column("usage_records", "cost_micro_cents")
    op.drop_column("audit_events", "signing_key_id")
