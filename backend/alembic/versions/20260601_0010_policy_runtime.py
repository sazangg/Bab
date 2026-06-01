"""Policy runtime attribution.

Revision ID: 20260601_0010
Revises: 20260601_0009
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260601_0010"
down_revision: str | None = "20260601_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    usage_columns = {column["name"] for column in inspector.get_columns("usage_records")}
    virtual_key_columns = {column["name"] for column in inspector.get_columns("virtual_keys")}
    reservation_columns = (
        {column["name"] for column in inspector.get_columns("allocation_reservations")}
        if "allocation_reservations" in table_names
        else set()
    )

    if "allocation_id" in virtual_key_columns:
        with op.batch_alter_table("virtual_keys") as batch:
            batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=True)

    if "allocation_id" in usage_columns:
        with op.batch_alter_table("usage_records") as batch:
            batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=True)

    if "access_policy_id" not in usage_columns:
        with op.batch_alter_table("usage_records") as batch:
            batch.add_column(sa.Column("access_policy_id", sa.Uuid(), nullable=True))
            batch.add_column(sa.Column("access_policy_route_id", sa.Uuid(), nullable=True))
            batch.add_column(sa.Column("limit_policy_ids", sa.JSON(), nullable=True))
            batch.create_index("ix_usage_records_access_policy_id", ["access_policy_id"])
            batch.create_index(
                "ix_usage_records_access_policy_route_id",
                ["access_policy_route_id"],
            )

    if "allocation_reservations" not in table_names:
        return

    if "allocation_id" in reservation_columns:
        with op.batch_alter_table("allocation_reservations") as batch:
            batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=True)

    if "limit_policy_id" not in reservation_columns:
        with op.batch_alter_table("allocation_reservations") as batch:
            batch.add_column(sa.Column("limit_policy_id", sa.Uuid(), nullable=True))
            batch.create_index("ix_allocation_reservations_limit_policy_id", ["limit_policy_id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "allocation_reservations" in table_names:
        reservation_columns = {
            column["name"] for column in inspector.get_columns("allocation_reservations")
        }
        reservation_indexes = {
            index["name"] for index in inspector.get_indexes("allocation_reservations")
        }
        if "limit_policy_id" in reservation_columns:
            with op.batch_alter_table("allocation_reservations") as batch:
                if "ix_allocation_reservations_limit_policy_id" in reservation_indexes:
                    batch.drop_index("ix_allocation_reservations_limit_policy_id")
                batch.drop_column("limit_policy_id")

        if "allocation_id" in reservation_columns:
            with op.batch_alter_table("allocation_reservations") as batch:
                batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=False)

    usage_columns = {column["name"] for column in inspector.get_columns("usage_records")}
    usage_indexes = {index["name"] for index in inspector.get_indexes("usage_records")}
    with op.batch_alter_table("usage_records") as batch:
        if "ix_usage_records_access_policy_route_id" in usage_indexes:
            batch.drop_index("ix_usage_records_access_policy_route_id")
        if "ix_usage_records_access_policy_id" in usage_indexes:
            batch.drop_index("ix_usage_records_access_policy_id")
        for column_name in ("limit_policy_ids", "access_policy_route_id", "access_policy_id"):
            if column_name in usage_columns:
                batch.drop_column(column_name)

    if "allocation_id" in usage_columns:
        with op.batch_alter_table("usage_records") as batch:
            batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=False)

    virtual_key_columns = {column["name"] for column in inspector.get_columns("virtual_keys")}
    if "allocation_id" in virtual_key_columns:
        with op.batch_alter_table("virtual_keys") as batch:
            batch.alter_column("allocation_id", existing_type=sa.Uuid(), nullable=False)
