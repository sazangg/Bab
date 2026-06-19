"""Add gateway route attempts and policy decisions.

Revision ID: 20260617_0035
Revises: 20260617_0034
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260617_0035"
down_revision: str | None = "20260617_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if _has_table("gateway_requests"):
        if not _has_column("gateway_requests", "public_model_id"):
            op.add_column(
                "gateway_requests", sa.Column("public_model_id", sa.Uuid(), nullable=True)
            )
            op.create_index(
                "ix_gateway_requests_public_model_id", "gateway_requests", ["public_model_id"]
            )
        if not _has_column("gateway_requests", "final_route_attempt_id"):
            op.add_column(
                "gateway_requests",
                sa.Column("final_route_attempt_id", sa.Uuid(), nullable=True),
            )
            op.create_index(
                "ix_gateway_requests_final_route_attempt_id",
                "gateway_requests",
                ["final_route_attempt_id"],
            )
        if not _has_column("gateway_requests", "trace_expires_at"):
            op.add_column(
                "gateway_requests",
                sa.Column(
                    "trace_expires_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                ),
            )
            op.create_index(
                "ix_gateway_requests_trace_expires_at", "gateway_requests", ["trace_expires_at"]
            )

    if not _has_table("gateway_route_attempts"):
        op.create_table(
            "gateway_route_attempts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("gateway_request_id", sa.Uuid(), nullable=False),
            sa.Column("attempt_index", sa.Integer(), nullable=False),
            sa.Column("access_policy_id", sa.Uuid(), nullable=True),
            sa.Column("access_policy_revision_id", sa.Uuid(), nullable=True),
            sa.Column("access_public_model_id", sa.Uuid(), nullable=True),
            sa.Column("route_candidate_id", sa.Uuid(), nullable=True),
            sa.Column("primary_route_candidate_id", sa.Uuid(), nullable=True),
            sa.Column("provider_id", sa.Uuid(), nullable=True),
            sa.Column("provider_name", sa.String(length=255), nullable=True),
            sa.Column("provider_slug", sa.String(length=100), nullable=True),
            sa.Column("credential_pool_id", sa.Uuid(), nullable=True),
            sa.Column("credential_pool_name", sa.String(length=255), nullable=True),
            sa.Column("provider_credential_id", sa.Uuid(), nullable=True),
            sa.Column("provider_credential_name", sa.String(length=255), nullable=True),
            sa.Column("provider_credential_prefix", sa.String(length=20), nullable=True),
            sa.Column("provider_model_offering_id", sa.Uuid(), nullable=True),
            sa.Column("provider_model", sa.String(length=255), nullable=True),
            sa.Column("public_model_name", sa.String(length=255), nullable=True),
            sa.Column("fallback_from_attempt_id", sa.Uuid(), nullable=True),
            sa.Column("fallback_trigger_reason", sa.String(length=100), nullable=True),
            sa.Column("skipped_reason", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=100), nullable=True),
            sa.Column("failure_reason", sa.String(length=100), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("cost_cents", sa.Integer(), nullable=True),
            sa.Column("cost_micro_cents", sa.BigInteger(), nullable=True),
            sa.Column("usage_source", sa.String(length=50), nullable=False),
            sa.Column("pricing_snapshot", sa.JSON(), nullable=False),
            sa.Column("capability_snapshot", sa.JSON(), nullable=False),
            sa.Column("route_snapshot", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["access_policy_id"], ["policies.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["access_policy_revision_id"], ["policy_revisions.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["access_public_model_id"], ["access_policy_public_models.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["credential_pool_id"], ["credential_pools.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["fallback_from_attempt_id"], ["gateway_route_attempts.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["gateway_request_id"], ["gateway_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["primary_route_candidate_id"],
                ["access_policy_route_candidates.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["provider_credential_id"], ["provider_credentials.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["provider_model_offering_id"], ["provider_model_offerings.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["route_candidate_id"], ["access_policy_route_candidates.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in {
            "ix_gateway_route_attempts_org_id": ["org_id"],
            "ix_gateway_route_attempts_gateway_request_id": ["gateway_request_id"],
            "ix_gateway_route_attempts_access_policy_id": ["access_policy_id"],
            "ix_gateway_route_attempts_access_policy_revision_id": ["access_policy_revision_id"],
            "ix_gateway_route_attempts_access_public_model_id": ["access_public_model_id"],
            "ix_gateway_route_attempts_route_candidate_id": ["route_candidate_id"],
            "ix_gateway_route_attempts_provider_id": ["provider_id"],
            "ix_gateway_route_attempts_credential_pool_id": ["credential_pool_id"],
            "ix_gateway_route_attempts_provider_credential_id": ["provider_credential_id"],
            "ix_gateway_route_attempts_provider_model_offering_id": ["provider_model_offering_id"],
            "ix_gateway_route_attempts_fallback_from_attempt_id": ["fallback_from_attempt_id"],
            "ix_gateway_route_attempts_status": ["status"],
            "ix_gateway_route_attempts_started_at": ["started_at"],
        }.items():
            op.create_index(name, "gateway_route_attempts", columns)

    if not _has_table("gateway_policy_decisions"):
        op.create_table(
            "gateway_policy_decisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("gateway_request_id", sa.Uuid(), nullable=False),
            sa.Column("route_attempt_id", sa.Uuid(), nullable=True),
            sa.Column("decision_type", sa.String(length=50), nullable=False),
            sa.Column("stage", sa.String(length=50), nullable=False),
            sa.Column("outcome", sa.String(length=50), nullable=False),
            sa.Column("effective_action", sa.String(length=50), nullable=True),
            sa.Column("enforced", sa.Boolean(), nullable=False),
            sa.Column("policy_id", sa.Uuid(), nullable=True),
            sa.Column("policy_revision_id", sa.Uuid(), nullable=True),
            sa.Column("assignment_id", sa.Uuid(), nullable=True),
            sa.Column("assignment_mode", sa.String(length=50), nullable=True),
            sa.Column("assignment_scope_type", sa.String(length=50), nullable=True),
            sa.Column("assignment_team_id", sa.Uuid(), nullable=True),
            sa.Column("assignment_project_id", sa.Uuid(), nullable=True),
            sa.Column("assignment_virtual_key_id", sa.Uuid(), nullable=True),
            sa.Column("rule_id", sa.Uuid(), nullable=True),
            sa.Column("route_candidate_id", sa.Uuid(), nullable=True),
            sa.Column("reason_code", sa.String(length=100), nullable=True),
            sa.Column("message", sa.String(length=1000), nullable=True),
            sa.Column("dimension_snapshot", sa.JSON(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["assignment_id"], ["policy_assignments.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["gateway_request_id"], ["gateway_requests.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["policy_id"], ["policies.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["policy_revision_id"], ["policy_revisions.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["route_attempt_id"], ["gateway_route_attempts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["route_candidate_id"], ["access_policy_route_candidates.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in {
            "ix_gateway_policy_decisions_org_id": ["org_id"],
            "ix_gateway_policy_decisions_gateway_request_id": ["gateway_request_id"],
            "ix_gateway_policy_decisions_route_attempt_id": ["route_attempt_id"],
            "ix_gateway_policy_decisions_decision_type": ["decision_type"],
            "ix_gateway_policy_decisions_stage": ["stage"],
            "ix_gateway_policy_decisions_outcome": ["outcome"],
            "ix_gateway_policy_decisions_policy_id": ["policy_id"],
            "ix_gateway_policy_decisions_policy_revision_id": ["policy_revision_id"],
            "ix_gateway_policy_decisions_assignment_id": ["assignment_id"],
            "ix_gateway_policy_decisions_rule_id": ["rule_id"],
            "ix_gateway_policy_decisions_route_candidate_id": ["route_candidate_id"],
            "ix_gateway_policy_decisions_created_at": ["created_at"],
        }.items():
            op.create_index(name, "gateway_policy_decisions", columns)

    if (
        _has_table("gateway_requests")
        and _has_table("gateway_route_attempts")
        and _has_column("gateway_requests", "final_route_attempt_id")
        and not _has_foreign_key(
            "gateway_requests",
            "fk_gateway_requests_final_route_attempt_id_gateway_route_attempts",
        )
    ):
        with op.batch_alter_table("gateway_requests") as batch_op:
            batch_op.create_foreign_key(
                "fk_gateway_requests_final_route_attempt_id_gateway_route_attempts",
                "gateway_route_attempts",
                ["final_route_attempt_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    for table_name in ("gateway_policy_decisions", "gateway_route_attempts"):
        if _has_table(table_name):
            op.drop_table(table_name)
    if _has_table("gateway_requests"):
        for index_name in (
            "ix_gateway_requests_trace_expires_at",
            "ix_gateway_requests_final_route_attempt_id",
            "ix_gateway_requests_public_model_id",
        ):
            if _has_index("gateway_requests", index_name):
                op.drop_index(index_name, table_name="gateway_requests")
        for column_name in ("trace_expires_at", "final_route_attempt_id", "public_model_id"):
            if _has_column("gateway_requests", column_name):
                op.drop_column("gateway_requests", column_name)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        foreign_key["name"] == constraint_name
        for foreign_key in inspect(op.get_bind()).get_foreign_keys(table_name)
    )
