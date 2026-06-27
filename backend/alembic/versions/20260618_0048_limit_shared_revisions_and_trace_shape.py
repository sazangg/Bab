"""Align limit policies and gateway traces with shared policy foundation.

Revision ID: 20260618_0048
Revises: 20260618_0047
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op

revision: str = "20260618_0048"
down_revision: str | None = "20260618_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("limit_policy_committed_usage"):
        op.create_table(
            "limit_policy_committed_usage",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("usage_record_id", sa.Uuid(), nullable=False),
            sa.Column("limit_policy_id", sa.Uuid(), nullable=False),
            sa.Column("limit_policy_revision_id", sa.Uuid(), nullable=False),
            sa.Column("limit_policy_rule_id", sa.Uuid(), nullable=False),
            sa.Column("limit_policy_assignment_id", sa.Uuid(), nullable=False),
            sa.Column("counter_key", sa.String(length=500), nullable=True),
            sa.Column("counting_unit", sa.String(length=50), nullable=False),
            sa.Column("window_descriptor", sa.String(length=150), nullable=True),
            sa.Column("dimension_snapshot", sa.JSON(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("cost_cents", sa.Integer(), nullable=True),
            sa.Column("cost_micro_cents", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["usage_record_id"], ["usage_records.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["limit_policy_id"], ["limit_policies.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["limit_policy_revision_id"], ["policy_revisions.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["limit_policy_rule_id"], ["limit_policy_rules.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["limit_policy_assignment_id"], ["policy_assignments.id"], ondelete="RESTRICT"
            ),
        )
        for name, columns in {
            "ix_limit_policy_committed_usage_org_id": ["org_id"],
            "ix_limit_policy_committed_usage_usage_record_id": ["usage_record_id"],
            "ix_limit_policy_committed_usage_limit_policy_id": ["limit_policy_id"],
            "ix_limit_policy_committed_usage_limit_policy_revision_id": [
                "limit_policy_revision_id"
            ],
            "ix_limit_policy_committed_usage_limit_policy_rule_id": ["limit_policy_rule_id"],
            "ix_limit_policy_committed_usage_limit_policy_assignment_id": [
                "limit_policy_assignment_id"
            ],
            "ix_limit_policy_committed_usage_counter_key": ["counter_key"],
            "ix_limit_policy_committed_usage_window_descriptor": ["window_descriptor"],
            "ix_limit_policy_committed_usage_created_at": ["created_at"],
        }.items():
            op.create_index(name, "limit_policy_committed_usage", columns)

    if _has_table("limit_policies") and not _has_column("limit_policies", "policy_id"):
        op.add_column("limit_policies", sa.Column("policy_id", sa.Uuid(), nullable=False))
        op.create_index("ix_limit_policies_policy_id", "limit_policies", ["policy_id"], unique=True)
        _create_fk(
            "fk_limit_policies_policy_id_policies",
            "limit_policies",
            "policies",
            ["policy_id"],
            ["id"],
            ondelete="CASCADE",
        )
    elif _has_table("limit_policies"):
        with op.batch_alter_table("limit_policies") as batch_op:
            batch_op.alter_column("policy_id", existing_type=sa.Uuid(), nullable=False)

    if _has_table("limit_policy_rules") and not _has_column(
        "limit_policy_rules", "policy_revision_id"
    ):
        op.add_column(
            "limit_policy_rules", sa.Column("policy_revision_id", sa.Uuid(), nullable=False)
        )
        op.create_index(
            "ix_limit_policy_rules_policy_revision_id",
            "limit_policy_rules",
            ["policy_revision_id"],
        )
        _create_fk(
            "fk_limit_policy_rules_policy_revision_id_policy_revisions",
            "limit_policy_rules",
            "policy_revisions",
            ["policy_revision_id"],
            ["id"],
            ondelete="CASCADE",
        )
    elif _has_table("limit_policy_rules"):
        with op.batch_alter_table("limit_policy_rules") as batch_op:
            batch_op.alter_column("policy_revision_id", existing_type=sa.Uuid(), nullable=False)

    if _has_table("limit_policy_reservations") and not _has_column(
        "limit_policy_reservations", "limit_policy_revision_id"
    ):
        op.add_column(
            "limit_policy_reservations",
            sa.Column("limit_policy_revision_id", sa.Uuid(), nullable=False),
        )
        op.create_index(
            "ix_limit_policy_reservations_limit_policy_revision_id",
            "limit_policy_reservations",
            ["limit_policy_revision_id"],
        )
        _create_fk(
            "fk_limit_policy_reservations_limit_policy_revision_id_policy_revisions",
            "limit_policy_reservations",
            "policy_revisions",
            ["limit_policy_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    elif _has_table("limit_policy_reservations"):
        with op.batch_alter_table("limit_policy_reservations") as batch_op:
            batch_op.alter_column(
                "limit_policy_revision_id",
                existing_type=sa.Uuid(),
                nullable=False,
            )

    _backfill_limit_shared_identity()
    _backfill_access_runtime_shared_identity()
    _backfill_policy_assignments()


def downgrade() -> None:
    if _has_table("limit_policy_committed_usage"):
        op.drop_table("limit_policy_committed_usage")
    for table_name, column_name, index_name in (
        (
            "limit_policy_reservations",
            "limit_policy_revision_id",
            "ix_limit_policy_reservations_limit_policy_revision_id",
        ),
        ("limit_policy_rules", "policy_revision_id", "ix_limit_policy_rules_policy_revision_id"),
        ("limit_policies", "policy_id", "ix_limit_policies_policy_id"),
    ):
        if _has_table(table_name):
            if _has_index(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)
            if _has_column(table_name, column_name):
                op.drop_column(table_name, column_name)


def _backfill_limit_shared_identity() -> None:
    if not all(
        _has_table(table_name)
        for table_name in ("limit_policies", "limit_policy_rules", "policies", "policy_revisions")
    ):
        return
    connection = op.get_bind()
    rows = connection.execute(
        text(
            "select id, org_id, name, description, is_active, created_at, updated_at "
            "from limit_policies where policy_id is null"
        )
    ).mappings()
    for row in rows:
        policy_id = _uuid_sql()
        revision_id = _uuid_sql()
        connection.execute(
            text(
                "insert into policies "
                "(id, org_id, kind, name, description, is_active, created_at, updated_at) "
                "values (:id, :org_id, 'limit', :name, :description, :is_active, "
                ":created_at, :updated_at)"
            ),
            {
                "id": policy_id,
                "org_id": row["org_id"],
                "name": row["name"],
                "description": row["description"],
                "is_active": row["is_active"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
        connection.execute(
            text(
                "insert into policy_revisions "
                "(id, org_id, policy_id, revision_number, status, created_by, created_at, "
                "activated_at, archived_at) "
                "values (:id, :org_id, :policy_id, 1, 'active', null, :created_at, "
                ":created_at, null)"
            ),
            {
                "id": revision_id,
                "org_id": row["org_id"],
                "policy_id": policy_id,
                "created_at": row["created_at"],
            },
        )
        connection.execute(
            text("update limit_policies set policy_id = :policy_id where id = :id"),
            {"policy_id": policy_id, "id": row["id"]},
        )
        connection.execute(
            text(
                "update limit_policy_rules set policy_revision_id = :revision_id "
                "where limit_policy_id = :limit_policy_id and policy_revision_id is null"
            ),
            {"revision_id": revision_id, "limit_policy_id": row["id"]},
        )


def _backfill_policy_assignments() -> None:
    if not all(_has_table(table_name) for table_name in ("policy_assignments", "access_policies")):
        return
    required_columns = ("policy_id", "scope_target_key", "effective_from", "effective_to")
    if not all(_has_column("policy_assignments", column_name) for column_name in required_columns):
        return
    connection = op.get_bind()
    connection.execute(
        text(
            "update policy_assignments "
            "set scope_target_key = case "
            "when scope_type = 'org' then 'org' "
            "when scope_type = 'team' then 'team:' || team_id "
            "when scope_type = 'project' then 'project:' || project_id "
            "when scope_type = 'virtual_key' then 'virtual_key:' || virtual_key_id "
            "else scope_target_key end "
            "where scope_target_key is null"
        )
    )
    connection.execute(
        text(
            "update policy_assignments "
            "set effective_from = coalesce(effective_from, created_at) "
            "where effective_from is null"
        )
    )
    connection.execute(
        text(
            "update policy_assignments "
            "set effective_to = coalesce(effective_to, updated_at, created_at) "
            "where is_active = false and effective_to is null"
        )
    )


def _backfill_access_runtime_shared_identity() -> None:
    if not all(_has_table(table_name) for table_name in ("access_policies", "policies")):
        return
    connection = op.get_bind()
    if _has_table("usage_records") and _has_column("usage_records", "access_policy_id"):
        connection.execute(
            text(
                "update usage_records "
                "set access_policy_id = ("
                "select access_policies.policy_id from access_policies "
                "where access_policies.id = usage_records.access_policy_id"
                ") "
                "where access_policy_id is not null "
                "and exists ("
                "select 1 from access_policies "
                "where access_policies.id = usage_records.access_policy_id "
                "and access_policies.policy_id is not null"
                ")"
            )
        )
        if not _has_foreign_key_to("usage_records", "access_policy_id", "policies"):
            _create_fk(
                "fk_usage_records_access_policy_id_policies",
                "usage_records",
                "policies",
                ["access_policy_id"],
                ["id"],
                ondelete="RESTRICT",
            )
    if _has_table("gateway_requests") and _has_column(
        "gateway_requests", "final_access_policy_id"
    ):
        connection.execute(
            text(
                "update gateway_requests "
                "set final_access_policy_id = ("
                "select access_policies.policy_id from access_policies "
                "where access_policies.id = gateway_requests.final_access_policy_id"
                ") "
                "where final_access_policy_id is not null "
                "and exists ("
                "select 1 from access_policies "
                "where access_policies.id = gateway_requests.final_access_policy_id "
                "and access_policies.policy_id is not null"
                ")"
            )
        )
        if not _has_foreign_key_to("gateway_requests", "final_access_policy_id", "policies"):
            _create_fk(
                "fk_gateway_requests_final_access_policy_id_policies",
                "gateway_requests",
                "policies",
                ["final_access_policy_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def _uuid_sql() -> str:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return str(bind.execute(text("select gen_random_uuid()")).scalar_one())
    return str(bind.execute(text("select lower(hex(randomblob(4))) || '-' || "
                                 "lower(hex(randomblob(2))) || '-4' || "
                                 "substr(lower(hex(randomblob(2))), 2) || '-' || "
                                 "substr('89ab', abs(random()) % 4 + 1, 1) || "
                                 "substr(lower(hex(randomblob(2))), 2) || '-' || "
                                 "lower(hex(randomblob(6)))")).scalar_one())


def _create_fk(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    *,
    ondelete: str,
) -> None:
    if _has_foreign_key(source_table, constraint_name):
        return
    with op.batch_alter_table(source_table) as batch_op:
        batch_op.create_foreign_key(
            constraint_name,
            referent_table,
            local_cols,
            remote_cols,
            ondelete=ondelete,
        )


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


def _has_foreign_key_to(table_name: str, column_name: str, referred_table: str) -> bool:
    return any(
        foreign_key["referred_table"] == referred_table
        and foreign_key["constrained_columns"] == [column_name]
        for foreign_key in inspect(op.get_bind()).get_foreign_keys(table_name)
    )


