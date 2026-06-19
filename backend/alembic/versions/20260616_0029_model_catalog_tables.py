"""Add model catalog entries and provider mappings.

Revision ID: 20260616_0029
Revises: 20260616_0028
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260616_0029"
down_revision: str | None = "20260616_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("model_catalog_entries"):
        op.create_table(
            "model_catalog_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("canonical_name", sa.String(length=255), nullable=False),
            sa.Column("family", sa.String(length=255), nullable=True),
            sa.Column("provider_family", sa.String(length=255), nullable=False),
            sa.Column("version", sa.String(length=100), nullable=True),
            sa.Column("input_modalities", sa.JSON(), nullable=False),
            sa.Column("output_modalities", sa.JSON(), nullable=False),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("context_window", sa.Integer(), nullable=True),
            sa.Column("input_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("output_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("cached_input_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("pricing_currency", sa.String(length=20), nullable=False),
            sa.Column("pricing_unit", sa.String(length=50), nullable=False),
            sa.Column("catalog_version", sa.String(length=100), nullable=False),
            sa.Column("metadata_source", sa.String(length=100), nullable=False),
            sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "provider_family <> ''", name="ck_model_catalog_entries_provider_family"
            ),
            sa.CheckConstraint(
                "catalog_version <> ''", name="ck_model_catalog_entries_catalog_version"
            ),
            sa.CheckConstraint(
                "pricing_currency = 'USD'", name="ck_model_catalog_entries_currency"
            ),
            sa.CheckConstraint(
                "pricing_unit = 'million_tokens'", name="ck_model_catalog_entries_unit"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "canonical_name",
                "provider_family",
                "metadata_source",
                "catalog_version",
                name="uq_model_catalog_entry_source_version",
            ),
        )
        for name, columns in {
            "ix_model_catalog_entries_canonical_name": ["canonical_name"],
            "ix_model_catalog_entries_family": ["family"],
            "ix_model_catalog_entries_provider_family": ["provider_family"],
            "ix_model_catalog_entries_is_active": ["is_active"],
        }.items():
            op.create_index(name, "model_catalog_entries", columns)

    if not _has_table("provider_model_catalog_mappings"):
        op.create_table(
            "provider_model_catalog_mappings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("provider_id", sa.Uuid(), nullable=False),
            sa.Column("provider_model_offering_id", sa.Uuid(), nullable=False),
            sa.Column("catalog_entry_id", sa.Uuid(), nullable=False),
            sa.Column("match_source", sa.String(length=100), nullable=False),
            sa.Column("confidence", sa.String(length=50), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column("input_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("output_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("cached_input_price_per_million_tokens", sa.Integer(), nullable=True),
            sa.Column("pricing_currency", sa.String(length=20), nullable=True),
            sa.Column("pricing_unit", sa.String(length=50), nullable=True),
            sa.Column("pricing_source", sa.String(length=100), nullable=True),
            sa.Column("pricing_last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "pricing_currency IS NULL OR pricing_currency = 'USD'",
                name="ck_provider_model_catalog_mappings_currency",
            ),
            sa.CheckConstraint(
                "pricing_unit IS NULL OR pricing_unit = 'million_tokens'",
                name="ck_provider_model_catalog_mappings_unit",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_entry_id"], ["model_catalog_entries.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["provider_model_offering_id"],
                ["provider_model_offerings.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider_model_offering_id",
                "catalog_entry_id",
                "match_source",
                name="uq_provider_model_catalog_mapping_match",
            ),
        )
        for name, columns in {
            "ix_provider_model_catalog_mappings_org_id": ["org_id"],
            "ix_provider_model_catalog_mappings_provider_id": ["provider_id"],
            "ix_provider_model_catalog_mappings_provider_model_offering_id": [
                "provider_model_offering_id"
            ],
            "ix_provider_model_catalog_mappings_catalog_entry_id": ["catalog_entry_id"],
        }.items():
            op.create_index(name, "provider_model_catalog_mappings", columns)
        op.create_index(
            "uq_provider_model_catalog_mappings_primary_active",
            "provider_model_catalog_mappings",
            ["provider_model_offering_id"],
            unique=True,
            sqlite_where=sa.text("is_active = 1 AND is_primary = 1"),
            postgresql_where=sa.text("is_active = true AND is_primary = true"),
        )


def downgrade() -> None:
    for table_name in ("provider_model_catalog_mappings", "model_catalog_entries"):
        if _has_table(table_name):
            op.drop_table(table_name)


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)
