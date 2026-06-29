"""Add composite indexes for backend performance hot paths.

Revision ID: 20260620_0050
Revises: 20260619_0049
Create Date: 2026-06-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260620_0050"
down_revision: str | None = "20260619_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_usage_records_org_created_at_id", "usage_records", ["org_id", "created_at", "id"]),
    (
        "ix_usage_records_org_provider_created_at",
        "usage_records",
        ["org_id", "provider_id", "created_at"],
    ),
    (
        "ix_usage_records_org_project_created_at",
        "usage_records",
        ["org_id", "project_id", "created_at"],
    ),
    (
        "ix_usage_records_org_virtual_key_created_at",
        "usage_records",
        ["org_id", "virtual_key_id", "created_at"],
    ),
    (
        "ix_gateway_requests_org_started_id",
        "gateway_requests",
        ["org_id", "started_at", "id"],
    ),
    (
        "ix_gateway_route_attempts_org_request_attempt",
        "gateway_route_attempts",
        ["org_id", "gateway_request_id", "attempt_index", "started_at", "id"],
    ),
    (
        "ix_gateway_policy_decisions_org_request_created",
        "gateway_policy_decisions",
        ["org_id", "gateway_request_id", "created_at", "id"],
    ),
    (
        "ix_policy_assignments_org_type_active_created",
        "policy_assignments",
        ["org_id", "policy_type", "is_active", "created_at"],
    ),
    ("ix_virtual_keys_org_created_id", "virtual_keys", ["org_id", "created_at", "id"]),
    (
        "ix_virtual_keys_org_project_created_id",
        "virtual_keys",
        ["org_id", "project_id", "created_at", "id"],
    ),
    (
        "ix_limit_committed_rule_counter_window_created",
        "limit_policy_committed_usage",
        ["limit_policy_rule_id", "counter_key", "window_descriptor", "created_at"],
    ),
    (
        "ix_limit_reservations_rule_counter_status_expires",
        "limit_policy_reservations",
        ["limit_policy_rule_id", "counter_key", "status", "expires_at"],
    ),
    (
        "ix_limit_reservations_assignment_status_expires",
        "limit_policy_reservations",
        ["limit_policy_assignment_id", "status", "expires_at"],
    ),
)


def upgrade() -> None:
    for index_name, table_name, columns in INDEXES:
        op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    for index_name, table_name, _columns in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
