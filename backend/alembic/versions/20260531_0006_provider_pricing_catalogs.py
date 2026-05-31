"""Add provider pricing catalog fields.

Revision ID: 20260531_0006
Revises: 20260531_0005
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260531_0006"
down_revision: str | None = "20260531_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("model_offerings")}
    _add_column_if_missing(
        columns,
        "catalog_input_price_per_million_tokens",
        sa.Column("catalog_input_price_per_million_tokens", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        columns,
        "catalog_output_price_per_million_tokens",
        sa.Column("catalog_output_price_per_million_tokens", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        columns,
        "catalog_cached_input_price_per_million_tokens",
        sa.Column("catalog_cached_input_price_per_million_tokens", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        columns,
        "pricing_catalog_version",
        sa.Column("pricing_catalog_version", sa.String(length=100), nullable=True),
    )
    _add_column_if_missing(
        columns,
        "pricing_last_refreshed_at",
        sa.Column("pricing_last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE model_offerings
        SET
            catalog_input_price_per_million_tokens = input_price_per_million_tokens,
            catalog_output_price_per_million_tokens = output_price_per_million_tokens,
            catalog_cached_input_price_per_million_tokens = cached_input_price_per_million_tokens,
            input_price_per_million_tokens = NULL,
            output_price_per_million_tokens = NULL,
            cached_input_price_per_million_tokens = NULL,
            pricing_last_refreshed_at = metadata_last_synced_at
        WHERE metadata_source = 'catalog'
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("model_offerings")}
    for column_name in (
        "pricing_last_refreshed_at",
        "pricing_catalog_version",
        "catalog_cached_input_price_per_million_tokens",
        "catalog_output_price_per_million_tokens",
        "catalog_input_price_per_million_tokens",
    ):
        if column_name in columns:
            op.drop_column("model_offerings", column_name)


def _add_column_if_missing(columns: set[str], column_name: str, column: sa.Column) -> None:
    if column_name in columns:
        return
    op.add_column("model_offerings", column)
    columns.add(column_name)
