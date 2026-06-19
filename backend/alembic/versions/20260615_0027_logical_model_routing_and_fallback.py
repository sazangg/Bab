"""Add logical model routing and fallback tables.

Revision ID: 20260615_0027
Revises: 20260613_0026
Create Date: 2026-06-15
"""

import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260615_0027"
down_revision: str | None = "20260613_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    model_offerings_table = _model_offerings_table()
    if not _has_table("access_policy_public_models"):
        op.create_table(
            "access_policy_public_models",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("access_policy_id", sa.Uuid(), nullable=False),
            sa.Column("public_model_name", sa.String(length=255), nullable=False),
            sa.Column("routing_mode", sa.String(length=50), nullable=False),
            sa.Column("fallback_on", sa.JSON(), nullable=False),
            sa.Column("max_route_attempts", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["access_policy_id"], ["access_policies.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "access_policy_id",
                "public_model_name",
                name="uq_access_policy_public_models_policy_name",
            ),
        )
        for name, columns in {
            "ix_access_policy_public_models_org_id": ["org_id"],
            "ix_access_policy_public_models_public_model_name": ["public_model_name"],
            "ix_access_policy_public_models_access_policy_id": ["access_policy_id"],
            "ix_access_policy_public_models_is_active": ["is_active"],
            "ix_access_policy_public_models_org_public_name": ["org_id", "public_model_name"],
        }.items():
            op.create_index(name, "access_policy_public_models", columns)

    if not _has_table("access_policy_route_candidates"):
        op.create_table(
            "access_policy_route_candidates",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("public_model_id", sa.Uuid(), nullable=False),
            sa.Column("provider_id", sa.Uuid(), nullable=False),
            sa.Column("credential_pool_id", sa.Uuid(), nullable=False),
            sa.Column("model_offering_id", sa.Uuid(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["credential_pool_id"], ["credential_pools.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["model_offering_id"], [f"{model_offerings_table}.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["public_model_id"], ["access_policy_public_models.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "public_model_id",
                "provider_id",
                "credential_pool_id",
                "model_offering_id",
                name="uq_access_policy_route_candidates_route",
            ),
        )
        for name, columns in {
            "ix_access_policy_route_candidates_org_id": ["org_id"],
            "ix_access_policy_route_candidates_public_model_id": ["public_model_id"],
            "ix_access_policy_route_candidates_provider_id": ["provider_id"],
            "ix_access_policy_route_candidates_credential_pool_id": ["credential_pool_id"],
            "ix_access_policy_route_candidates_model_offering_id": ["model_offering_id"],
            "ix_access_policy_route_candidates_order": [
                "public_model_id",
                "priority",
                "created_at",
            ],
        }.items():
            op.create_index(name, "access_policy_route_candidates", columns)

    if not _has_table("gateway_requests"):
        op.create_table(
            "gateway_requests",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("team_id", sa.Uuid(), nullable=True),
            sa.Column("project_id", sa.Uuid(), nullable=True),
            sa.Column("virtual_key_id", sa.Uuid(), nullable=True),
            sa.Column("request_id", sa.String(length=100), nullable=True),
            sa.Column("gateway_endpoint", sa.String(length=50), nullable=False),
            sa.Column("requested_model", sa.String(length=255), nullable=False),
            sa.Column("public_model_name", sa.String(length=255), nullable=True),
            sa.Column("routing_mode", sa.String(length=50), nullable=True),
            sa.Column("final_http_status", sa.Integer(), nullable=True),
            sa.Column("final_access_policy_id", sa.Uuid(), nullable=True),
            sa.Column("final_public_model_id", sa.Uuid(), nullable=True),
            sa.Column("final_candidate_id", sa.Uuid(), nullable=True),
            sa.Column("final_provider_id", sa.Uuid(), nullable=True),
            sa.Column("final_credential_pool_id", sa.Uuid(), nullable=True),
            sa.Column("final_model_offering_id", sa.Uuid(), nullable=True),
            sa.Column("final_provider_model", sa.String(length=255), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("fallback_attempted", sa.Boolean(), nullable=False),
            sa.Column("final_error_code", sa.String(length=100), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["final_access_policy_id"], ["policies.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["final_candidate_id"], ["access_policy_route_candidates.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["final_credential_pool_id"], ["credential_pools.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["final_model_offering_id"], [f"{model_offerings_table}.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["final_public_model_id"], ["access_policy_public_models.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["final_provider_id"], ["providers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["virtual_key_id"], ["virtual_keys.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in {
            "ix_gateway_requests_org_id": ["org_id"],
            "ix_gateway_requests_started_at": ["started_at"],
            "ix_gateway_requests_org_started_at": ["org_id", "started_at"],
            "ix_gateway_requests_request_id": ["request_id"],
            "ix_gateway_requests_org_request_id": ["org_id", "request_id"],
            "ix_gateway_requests_virtual_key_id": ["virtual_key_id"],
            "ix_gateway_requests_org_virtual_key_id": ["org_id", "virtual_key_id"],
            "ix_gateway_requests_final_provider_id": ["final_provider_id"],
            "ix_gateway_requests_org_final_provider_id": ["org_id", "final_provider_id"],
            "ix_gateway_requests_public_model_name": ["public_model_name"],
            "ix_gateway_requests_org_public_model_name": ["org_id", "public_model_name"],
        }.items():
            op.create_index(name, "gateway_requests", columns)

    _backfill_public_models_from_legacy_routes()
    _add_usage_attempt_columns()


def downgrade() -> None:
    columns = _columns("usage_records")
    for index_name in (
        "ix_usage_records_gateway_request_id",
        "ix_usage_records_public_model_id",
        "ix_usage_records_route_candidate_id",
        "ix_usage_records_public_model_name",
    ):
        if index_name in _indexes("usage_records"):
            op.drop_index(index_name, table_name="usage_records")
    with op.batch_alter_table("usage_records") as batch_op:
        for column_name in (
            "gateway_endpoint",
            "attempt_failure_reason",
            "fallback_trigger_reason",
            "fallback_from_candidate_id",
            "primary_route_candidate_id",
            "is_final_attempt",
            "routing_attempt_index",
            "routing_mode",
            "public_model_name",
            "route_candidate_id",
            "public_model_id",
            "gateway_request_id",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
    for table_name in (
        "gateway_requests",
        "access_policy_route_candidates",
        "access_policy_public_models",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)


def _add_usage_attempt_columns() -> None:
    columns = _columns("usage_records")
    additions = [
        ("gateway_request_id", sa.Column("gateway_request_id", sa.Uuid(), nullable=True)),
        ("public_model_id", sa.Column("public_model_id", sa.Uuid(), nullable=True)),
        ("route_candidate_id", sa.Column("route_candidate_id", sa.Uuid(), nullable=True)),
        ("public_model_name", sa.Column("public_model_name", sa.String(length=255), nullable=True)),
        ("routing_mode", sa.Column("routing_mode", sa.String(length=50), nullable=True)),
        (
            "routing_attempt_index",
            sa.Column("routing_attempt_index", sa.Integer(), nullable=False, server_default="0"),
        ),
        (
            "is_final_attempt",
            sa.Column("is_final_attempt", sa.Boolean(), nullable=False, server_default=sa.true()),
        ),
        (
            "primary_route_candidate_id",
            sa.Column("primary_route_candidate_id", sa.Uuid(), nullable=True),
        ),
        (
            "fallback_from_candidate_id",
            sa.Column("fallback_from_candidate_id", sa.Uuid(), nullable=True),
        ),
        (
            "fallback_trigger_reason",
            sa.Column("fallback_trigger_reason", sa.String(length=100), nullable=True),
        ),
        (
            "attempt_failure_reason",
            sa.Column("attempt_failure_reason", sa.String(length=100), nullable=True),
        ),
        ("gateway_endpoint", sa.Column("gateway_endpoint", sa.String(length=50), nullable=True)),
    ]
    with op.batch_alter_table("usage_records") as batch_op:
        for column_name, column in additions:
            if column_name not in columns:
                batch_op.add_column(column)
        foreign_keys = _foreign_keys("usage_records")
        for constraint_name, local_column, remote_table in (
            ("fk_usage_records_gateway_request_id", "gateway_request_id", "gateway_requests"),
            (
                "fk_usage_records_public_model_id",
                "public_model_id",
                "access_policy_public_models",
            ),
            (
                "fk_usage_records_route_candidate_id",
                "route_candidate_id",
                "access_policy_route_candidates",
            ),
            (
                "fk_usage_records_primary_route_candidate_id",
                "primary_route_candidate_id",
                "access_policy_route_candidates",
            ),
            (
                "fk_usage_records_fallback_from_candidate_id",
                "fallback_from_candidate_id",
                "access_policy_route_candidates",
            ),
        ):
            if constraint_name not in foreign_keys:
                batch_op.create_foreign_key(
                    constraint_name,
                    remote_table,
                    [local_column],
                    ["id"],
                    ondelete="RESTRICT",
                )
    for name, column in {
        "ix_usage_records_gateway_request_id": "gateway_request_id",
        "ix_usage_records_public_model_id": "public_model_id",
        "ix_usage_records_route_candidate_id": "route_candidate_id",
        "ix_usage_records_public_model_name": "public_model_name",
    }.items():
        if name not in _indexes("usage_records"):
            op.create_index(name, "usage_records", [column])


def _backfill_public_models_from_legacy_routes() -> None:
    if not _has_table("access_policy_routes"):
        return
    if not _has_table("access_policy_public_models") or not _has_table(
        "access_policy_route_candidates"
    ):
        return
    bind = op.get_bind()
    model_offerings_table = _model_offerings_table()
    existing_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM access_policy_public_models")
    ).scalar()
    if existing_count:
        return
    routes = bind.execute(
        sa.text(
            """
            SELECT id, org_id, access_policy_id, provider_id, credential_pool_id,
                   model_offering_ids, priority, weight, is_active, created_at, updated_at
            FROM access_policy_routes
            ORDER BY created_at, id
            """
        )
    ).mappings()
    for route in routes:
        model_ids = route["model_offering_ids"] or []
        if isinstance(model_ids, str):
            model_ids = json.loads(model_ids)
        if not isinstance(model_ids, list):
            continue
        for offset, model_id in enumerate(model_ids):
            model = (
                bind.execute(
                    sa.text(
                        f"""
                    SELECT provider_model_name
                    FROM {model_offerings_table}
                    WHERE id = :model_id AND org_id = :org_id
                    """
                    ),
                    {"model_id": model_id, "org_id": route["org_id"]},
                )
                .mappings()
                .first()
            )
            if model is None:
                continue
            public_model_id = bind.execute(
                sa.text(
                    """
                    INSERT INTO access_policy_public_models (
                        id, org_id, access_policy_id, public_model_name, routing_mode,
                        fallback_on, max_route_attempts, is_active, created_at, updated_at
                    )
                    VALUES (
                        :id, :org_id, :access_policy_id, :public_model_name, 'single_route',
                        :fallback_on, 1, :is_active, :created_at, :updated_at
                    )
                    ON CONFLICT (access_policy_id, public_model_name) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": uuid4(),
                    "org_id": route["org_id"],
                    "access_policy_id": route["access_policy_id"],
                    "public_model_name": model["provider_model_name"],
                    "fallback_on": json.dumps([]),
                    "is_active": route["is_active"],
                    "created_at": route["created_at"],
                    "updated_at": route["updated_at"],
                },
            ).scalar()
            if public_model_id is None:
                public_model_id = bind.execute(
                    sa.text(
                        """
                        SELECT id
                        FROM access_policy_public_models
                        WHERE access_policy_id = :access_policy_id
                          AND public_model_name = :public_model_name
                        """
                    ),
                    {
                        "access_policy_id": route["access_policy_id"],
                        "public_model_name": model["provider_model_name"],
                    },
                ).scalar()
            bind.execute(
                sa.text(
                    """
                    INSERT INTO access_policy_route_candidates (
                        id, org_id, public_model_id, provider_id, credential_pool_id,
                        model_offering_id, priority, weight, is_active, created_at, updated_at
                    )
                    VALUES (
                        :id, :org_id, :public_model_id, :provider_id,
                        :credential_pool_id, :model_offering_id, :priority, :weight,
                        :is_active, :created_at, :updated_at
                    )
                    ON CONFLICT (
                        public_model_id, provider_id, credential_pool_id, model_offering_id
                    ) DO NOTHING
                    """
                ),
                {
                    "org_id": route["org_id"],
                    "id": uuid4(),
                    "public_model_id": public_model_id,
                    "provider_id": route["provider_id"],
                    "credential_pool_id": route["credential_pool_id"],
                    "model_offering_id": model_id,
                    "priority": route["priority"] + offset,
                    "weight": route["weight"],
                    "is_active": route["is_active"],
                    "created_at": route["created_at"],
                    "updated_at": route["updated_at"],
                },
            )


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _model_offerings_table() -> str:
    if _has_table("provider_model_offerings"):
        return "provider_model_offerings"
    return "model_offerings"


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _foreign_keys(table_name: str) -> set[str]:
    return {key["name"] for key in inspect(op.get_bind()).get_foreign_keys(table_name)}
