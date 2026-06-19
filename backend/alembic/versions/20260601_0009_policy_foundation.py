"""Add access and limit policy foundation.

Revision ID: 20260601_0009
Revises: 20260531_0008
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260601_0009"
down_revision: str | None = "20260531_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    model_offerings_table = _model_offerings_table()
    if not _has_table("access_policies"):
        op.create_table(
            "access_policies",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_access_policies_org_id", "access_policies", ["org_id"])

    if not _has_table("access_policy_routes"):
        op.create_table(
            "access_policy_routes",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("access_policy_id", sa.Uuid(), nullable=False),
            sa.Column("provider_id", sa.Uuid(), nullable=False),
            sa.Column("credential_pool_id", sa.Uuid(), nullable=False),
            sa.Column("model_offering_ids", sa.JSON(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["access_policy_id"], ["access_policies.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["credential_pool_id"], ["credential_pools.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        for column_name in (
            "org_id",
            "access_policy_id",
            "provider_id",
            "credential_pool_id",
        ):
            op.create_index(
                f"ix_access_policy_routes_{column_name}",
                "access_policy_routes",
                [column_name],
            )

    if not _has_table("limit_policies"):
        op.create_table(
            "limit_policies",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("budget_cents", sa.Integer(), nullable=True),
            sa.Column("max_requests", sa.Integer(), nullable=True),
            sa.Column("max_input_tokens", sa.Integer(), nullable=True),
            sa.Column("max_output_tokens", sa.Integer(), nullable=True),
            sa.Column("max_tokens_per_request", sa.Integer(), nullable=True),
            sa.Column("window", sa.String(length=50), nullable=False),
            sa.Column("provider_id", sa.Uuid(), nullable=True),
            sa.Column("credential_pool_id", sa.Uuid(), nullable=True),
            sa.Column("model_offering_id", sa.Uuid(), nullable=True),
            sa.Column("access_policy_id", sa.Uuid(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["access_policy_id"], ["access_policies.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["credential_pool_id"], ["credential_pools.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["model_offering_id"], [f"{model_offerings_table}.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        for column_name in (
            "org_id",
            "provider_id",
            "credential_pool_id",
            "model_offering_id",
            "access_policy_id",
        ):
            op.create_index(f"ix_limit_policies_{column_name}", "limit_policies", [column_name])

    if not _has_table("policy_assignments"):
        op.create_table(
            "policy_assignments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("policy_type", sa.String(length=20), nullable=False),
            sa.Column("access_policy_id", sa.Uuid(), nullable=True),
            sa.Column("limit_policy_id", sa.Uuid(), nullable=True),
            sa.Column("scope_type", sa.String(length=20), nullable=False),
            sa.Column("team_id", sa.Uuid(), nullable=True),
            sa.Column("project_id", sa.Uuid(), nullable=True),
            sa.Column("virtual_key_id", sa.Uuid(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["access_policy_id"], ["access_policies.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["limit_policy_id"], ["limit_policies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["virtual_key_id"], ["virtual_keys.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        for column_name in (
            "org_id",
            "policy_type",
            "access_policy_id",
            "limit_policy_id",
            "scope_type",
            "team_id",
            "project_id",
            "virtual_key_id",
        ):
            op.create_index(
                f"ix_policy_assignments_{column_name}",
                "policy_assignments",
                [column_name],
            )


def downgrade() -> None:
    for table_name in (
        "policy_assignments",
        "limit_policies",
        "access_policy_routes",
        "access_policies",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _model_offerings_table() -> str:
    if _has_table("provider_model_offerings"):
        return "provider_model_offerings"
    return "model_offerings"
