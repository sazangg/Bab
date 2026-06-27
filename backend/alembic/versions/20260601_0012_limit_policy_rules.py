"""Add limit policy rules.

Revision ID: 20260601_0012
Revises: 20260601_0011
Create Date: 2026-06-01
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op

revision: str = "20260601_0012"
down_revision: str | None = "20260601_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    model_offerings_table = _model_offerings_table()
    if not _has_table("limit_policy_rules"):
        op.create_table(
            "limit_policy_rules",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("limit_policy_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
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
            sa.ForeignKeyConstraint(["limit_policy_id"], ["limit_policies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["model_offering_id"], [f"{model_offerings_table}.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        for column_name in (
            "access_policy_id",
            "credential_pool_id",
            "limit_policy_id",
            "model_offering_id",
            "org_id",
            "provider_id",
        ):
            op.create_index(
                f"ix_limit_policy_rules_{column_name}",
                "limit_policy_rules",
                [column_name],
            )
    _backfill_default_rules()
    _add_column_if_missing(
        "usage_records", sa.Column("limit_policy_rule_ids", sa.JSON(), nullable=True)
    )
    _add_column_if_missing(
        "limit_policy_reservations",
        sa.Column("limit_policy_rule_id", sa.Uuid(), nullable=False),
    )
    if _has_table("limit_policy_reservations"):
        indexes = {
            index["name"]
            for index in inspect(op.get_bind()).get_indexes("limit_policy_reservations")
        }
        if "ix_limit_policy_reservations_limit_policy_rule_id" not in indexes:
            op.create_index(
                "ix_limit_policy_reservations_limit_policy_rule_id",
                "limit_policy_reservations",
                ["limit_policy_rule_id"],
            )


def downgrade() -> None:
    pass


def _backfill_default_rules() -> None:
    bind = op.get_bind()
    policies = bind.execute(text("SELECT * FROM limit_policies")).mappings().all()
    for policy in policies:
        policy_id = policy["id"]
        existing = bind.execute(
            text("SELECT id FROM limit_policy_rules WHERE limit_policy_id = :policy_id LIMIT 1"),
            {"policy_id": str(policy_id)},
        ).fetchone()
        if existing is not None:
            continue
        bind.execute(
            text(
                """
                INSERT INTO limit_policy_rules (
                    id, org_id, limit_policy_id, name, budget_cents, max_requests,
                    max_input_tokens, max_output_tokens, max_tokens_per_request,
                    window, provider_id, credential_pool_id, model_offering_id,
                    access_policy_id, is_active, created_at, updated_at
                )
                VALUES (
                    :id, :org_id, :limit_policy_id, :name, :budget_cents, :max_requests,
                    :max_input_tokens, :max_output_tokens, :max_tokens_per_request,
                    :window, :provider_id, :credential_pool_id, :model_offering_id,
                    :access_policy_id, :is_active, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org_id": str(policy["org_id"]),
                "limit_policy_id": str(policy_id),
                "name": "Default rule",
                "budget_cents": policy["budget_cents"],
                "max_requests": policy["max_requests"],
                "max_input_tokens": policy["max_input_tokens"],
                "max_output_tokens": policy["max_output_tokens"],
                "max_tokens_per_request": policy["max_tokens_per_request"],
                "window": policy["window"],
                "provider_id": None
                if policy["provider_id"] is None
                else str(policy["provider_id"]),
                "credential_pool_id": None
                if policy["credential_pool_id"] is None
                else str(policy["credential_pool_id"]),
                "model_offering_id": None
                if policy["model_offering_id"] is None
                else str(policy["model_offering_id"]),
                "access_policy_id": None
                if policy["access_policy_id"] is None
                else str(policy["access_policy_id"]),
                "is_active": policy["is_active"],
                "created_at": policy["created_at"],
                "updated_at": policy["updated_at"],
            },
        )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_table(table_name):
        return
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _has_table(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _model_offerings_table() -> str:
    if _has_table("provider_model_offerings"):
        return "provider_model_offerings"
    return "model_offerings"
