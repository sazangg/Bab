"""Use one-dimensional limit rules.

Revision ID: 20260602_0016
Revises: 20260602_0015
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260602_0016"
down_revision: str | Sequence[str] | None = "20260602_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    limit_policy_columns = _columns("limit_policies")
    with op.batch_alter_table("limit_policies") as batch:
        for column in (
            "budget_cents",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_tokens_per_request",
            "window",
            "provider_id",
            "credential_pool_id",
            "model_offering_id",
            "access_policy_id",
        ):
            if column in limit_policy_columns:
                batch.drop_column(column)

    rule_columns = _columns("limit_policy_rules")
    with op.batch_alter_table("limit_policy_rules") as batch:
        if "limit_type" not in rule_columns:
            batch.add_column(
                sa.Column("limit_type", sa.String(length=50), nullable=False, server_default="requests")
            )
        if "limit_value" not in rule_columns:
            batch.add_column(sa.Column("limit_value", sa.Integer(), nullable=False, server_default="1"))
        if "interval_unit" not in rule_columns:
            batch.add_column(
                sa.Column("interval_unit", sa.String(length=50), nullable=False, server_default="month")
            )
        if "interval_count" not in rule_columns:
            batch.add_column(sa.Column("interval_count", sa.Integer(), nullable=False, server_default="1"))
        for column in (
            "budget_cents",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_tokens_per_request",
            "window",
        ):
            if column in rule_columns:
                batch.drop_column(column)


def downgrade() -> None:
    rule_columns = _columns("limit_policy_rules")
    with op.batch_alter_table("limit_policy_rules") as batch:
        for column in ("limit_type", "limit_value", "interval_unit", "interval_count"):
            if column in rule_columns:
                batch.drop_column(column)
        batch.add_column(sa.Column("budget_cents", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_requests", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_input_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_output_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_tokens_per_request", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("window", sa.String(length=50), nullable=False, server_default="monthly"))

    limit_policy_columns = _columns("limit_policies")
    with op.batch_alter_table("limit_policies") as batch:
        if "budget_cents" not in limit_policy_columns:
            batch.add_column(sa.Column("budget_cents", sa.Integer(), nullable=True))
        if "max_requests" not in limit_policy_columns:
            batch.add_column(sa.Column("max_requests", sa.Integer(), nullable=True))
        if "max_input_tokens" not in limit_policy_columns:
            batch.add_column(sa.Column("max_input_tokens", sa.Integer(), nullable=True))
        if "max_output_tokens" not in limit_policy_columns:
            batch.add_column(sa.Column("max_output_tokens", sa.Integer(), nullable=True))
        if "max_tokens_per_request" not in limit_policy_columns:
            batch.add_column(sa.Column("max_tokens_per_request", sa.Integer(), nullable=True))
        if "window" not in limit_policy_columns:
            batch.add_column(sa.Column("window", sa.String(length=50), nullable=False, server_default="monthly"))
        if "provider_id" not in limit_policy_columns:
            batch.add_column(sa.Column("provider_id", sa.Uuid(), nullable=True))
        if "credential_pool_id" not in limit_policy_columns:
            batch.add_column(sa.Column("credential_pool_id", sa.Uuid(), nullable=True))
        if "model_offering_id" not in limit_policy_columns:
            batch.add_column(sa.Column("model_offering_id", sa.Uuid(), nullable=True))
        if "access_policy_id" not in limit_policy_columns:
            batch.add_column(sa.Column("access_policy_id", sa.Uuid(), nullable=True))
