"""Add scoped policy ownership and public app URL.

Revision ID: 20260609_0024
Revises: 20260609_0023
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260609_0024"
down_revision: str | None = "20260609_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _OwnerForeignKey:
    def __init__(self, column_name: str, referent_table: str, referent_column: str) -> None:
        self.column_name = column_name
        self.referent_table = referent_table
        self.referent_column = referent_column

    @property
    def signature(self) -> tuple[str, str, str]:
        return (self.column_name, self.referent_table, self.referent_column)

    def name(self, table_name: str) -> str:
        return f"fk_{table_name}_{self.column_name}_{self.referent_table}"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "organization_settings" in tables:
        _add_column_if_missing(
            inspector,
            "organization_settings",
            sa.Column("public_app_url", sa.String(length=500), nullable=True),
        )
    for table_name in ("access_policies", "limit_policies"):
        if table_name not in tables:
            continue
        _upgrade_policy_owner_columns_and_constraints(inspector, table_name)
        _create_index_if_missing(
            inspector,
            table_name,
            f"ix_{table_name}_owning_scope_type",
            ["owning_scope_type"],
        )
        _create_index_if_missing(
            inspector,
            table_name,
            f"ix_{table_name}_owning_team_id",
            ["owning_team_id"],
        )
        _create_index_if_missing(
            inspector, table_name, f"ix_{table_name}_owning_project_id", ["owning_project_id"]
        )
        _create_index_if_missing(
            inspector,
            table_name,
            f"ix_{table_name}_owning_virtual_key_id",
            ["owning_virtual_key_id"],
        )

def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "organization_settings" in inspector.get_table_names():
        _drop_column_if_present(inspector, "organization_settings", "public_app_url")
    for table_name in ("access_policies", "limit_policies"):
        if table_name not in inspector.get_table_names():
            continue
        for index_name in (
            f"ix_{table_name}_owning_virtual_key_id",
            f"ix_{table_name}_owning_project_id",
            f"ix_{table_name}_owning_team_id",
            f"ix_{table_name}_owning_scope_type",
        ):
            _drop_index_if_present(inspector, table_name, index_name)
        _downgrade_policy_owner_columns_and_constraints(inspector, table_name)


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def _drop_column_if_present(inspector, table_name: str, column_name: str) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column_name in columns:
        op.drop_column(table_name, column_name)


def _upgrade_policy_owner_columns_and_constraints(inspector, table_name: str) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    foreign_keys = _foreign_key_signatures(inspector, table_name)
    owner_columns = [
        sa.Column("owning_scope_type", sa.String(length=20), nullable=True),
        sa.Column("owning_team_id", sa.Uuid(), nullable=True),
        sa.Column("owning_project_id", sa.Uuid(), nullable=True),
        sa.Column("owning_virtual_key_id", sa.Uuid(), nullable=True),
    ]
    owner_foreign_keys = [
        _OwnerForeignKey("owning_team_id", "teams", "id"),
        _OwnerForeignKey("owning_project_id", "projects", "id"),
        _OwnerForeignKey("owning_virtual_key_id", "virtual_keys", "id"),
    ]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            for column in owner_columns:
                if column.name not in columns:
                    batch_op.add_column(column)
            for foreign_key in owner_foreign_keys:
                if foreign_key.signature not in foreign_keys:
                    batch_op.create_foreign_key(
                        foreign_key.name(table_name),
                        foreign_key.referent_table,
                        [foreign_key.column_name],
                        [foreign_key.referent_column],
                        ondelete="CASCADE",
                    )
        return
    for column in owner_columns:
        _add_column_if_missing(inspector, table_name, column)
    for foreign_key in owner_foreign_keys:
        if foreign_key.signature not in foreign_keys:
            op.create_foreign_key(
                foreign_key.name(table_name),
                table_name,
                foreign_key.referent_table,
                [foreign_key.column_name],
                [foreign_key.referent_column],
                ondelete="CASCADE",
            )


def _downgrade_policy_owner_columns_and_constraints(inspector, table_name: str) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    foreign_key_names = {item["name"] for item in inspector.get_foreign_keys(table_name)}
    owner_columns = (
        "owning_virtual_key_id",
        "owning_project_id",
        "owning_team_id",
        "owning_scope_type",
    )
    owner_foreign_keys = [
        _OwnerForeignKey("owning_virtual_key_id", "virtual_keys", "id"),
        _OwnerForeignKey("owning_project_id", "projects", "id"),
        _OwnerForeignKey("owning_team_id", "teams", "id"),
    ]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            for foreign_key in owner_foreign_keys:
                name = foreign_key.name(table_name)
                if name in foreign_key_names:
                    batch_op.drop_constraint(name, type_="foreignkey")
            for column_name in owner_columns:
                if column_name in columns:
                    batch_op.drop_column(column_name)
        return
    for foreign_key in owner_foreign_keys:
        name = foreign_key.name(table_name)
        if name in foreign_key_names:
            op.drop_constraint(name, table_name, type_="foreignkey")
    for column_name in owner_columns:
        _drop_column_if_present(inspector, table_name, column_name)


def _create_index_if_missing(
    inspector,
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    indexes = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def _drop_index_if_present(inspector, table_name: str, index_name: str) -> None:
    indexes = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name in indexes:
        op.drop_index(index_name, table_name=table_name)


def _foreign_key_signatures(inspector, table_name: str) -> set[tuple[str, str, str]]:
    signatures = set()
    for foreign_key in inspector.get_foreign_keys(table_name):
        constrained_columns = foreign_key.get("constrained_columns") or []
        referred_columns = foreign_key.get("referred_columns") or []
        referred_table = foreign_key.get("referred_table")
        if len(constrained_columns) == 1 and len(referred_columns) == 1 and referred_table:
            signatures.add((constrained_columns[0], referred_table, referred_columns[0]))
    return signatures
