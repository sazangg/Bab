"""Rename provider model offerings and remove alias fields.

Revision ID: 20260616_0028
Revises: 20260615_0027
Create Date: 2026-06-16
"""

from collections.abc import Sequence

from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0028"
down_revision: str | None = "20260615_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "model_offerings" in tables and "provider_model_offerings" not in tables:
        op.rename_table("model_offerings", "provider_model_offerings")

    if "provider_model_offerings" not in set(inspect(bind).get_table_names()):
        return

    columns = _columns("provider_model_offerings")
    with op.batch_alter_table("provider_model_offerings") as batch_op:
        for column_name in (
            "alias",
            "catalog_input_price_per_million_tokens",
            "catalog_output_price_per_million_tokens",
            "catalog_cached_input_price_per_million_tokens",
            "pricing_catalog_version",
            "pricing_last_refreshed_at",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)


def downgrade() -> None:
    bind = op.get_bind()
    if "provider_model_offerings" in set(inspect(bind).get_table_names()):
        op.rename_table("provider_model_offerings", "model_offerings")


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}
