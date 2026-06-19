import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_providers_org_slug"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    adapter_type: Mapped[str] = mapped_column(String(100), default="openai_compat")
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    supported_integration: Mapped[str] = mapped_column(String(100), default="openai_compatible")
    request_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_body_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_sync_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    circuit_breaker_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    max_concurrent_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
    )
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    key_prefix: Mapped[str] = mapped_column(String(20))
    api_key_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    secret_backend: Mapped[str] = mapped_column(String(100), default="local")
    secret_reference: Mapped[str] = mapped_column(String(500))
    health_status: Mapped[str] = mapped_column(String(50), default="unchecked")
    last_validation_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_validation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_successful_request_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CredentialPool(Base):
    __tablename__ = "credential_pools"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    selection_policy: Mapped[str] = mapped_column(String(100), default="priority")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CredentialPoolCredential(Base):
    __tablename__ = "credential_pool_credentials"
    __table_args__ = (
        UniqueConstraint(
            "pool_id",
            "provider_credential_id",
            name="uq_credential_pool_credential",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="CASCADE"),
        index=True,
    )
    provider_credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="CASCADE"),
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ModelOffering(Base):
    __tablename__ = "provider_model_offerings"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_model_name",
            name="uq_provider_model_offering_provider_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
    )
    provider_model_name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    modality: Mapped[str] = mapped_column(String(100), default="text")
    input_modalities: Mapped[list] = mapped_column(JSON, default=list)
    output_modalities: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_price_per_million_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    rate_limit_hints: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_source: Mapped[str] = mapped_column(String(100), default="manual")
    metadata_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ModelCatalogEntry(Base):
    __tablename__ = "model_catalog_entries"
    __table_args__ = (
        UniqueConstraint(
            "canonical_name",
            "provider_family",
            "metadata_source",
            "catalog_version",
            name="uq_model_catalog_entry_source_version",
        ),
        CheckConstraint("provider_family <> ''", name="ck_model_catalog_entries_provider_family"),
        CheckConstraint("catalog_version <> ''", name="ck_model_catalog_entries_catalog_version"),
        CheckConstraint("pricing_currency = 'USD'", name="ck_model_catalog_entries_currency"),
        CheckConstraint("pricing_unit = 'million_tokens'", name="ck_model_catalog_entries_unit"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    family: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_family: Mapped[str] = mapped_column(String(255), default="global", index=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_modalities: Mapped[list] = mapped_column(JSON, default=list)
    output_modalities: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_price_per_million_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pricing_currency: Mapped[str] = mapped_column(String(20), default="USD")
    pricing_unit: Mapped[str] = mapped_column(String(50), default="million_tokens")
    catalog_version: Mapped[str] = mapped_column(String(100), default="unversioned")
    metadata_source: Mapped[str] = mapped_column(String(100))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProviderModelCatalogMapping(Base):
    __tablename__ = "provider_model_catalog_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider_model_offering_id",
            "catalog_entry_id",
            "match_source",
            name="uq_provider_model_catalog_mapping_match",
        ),
        CheckConstraint(
            "pricing_currency IS NULL OR pricing_currency = 'USD'",
            name="ck_provider_model_catalog_mappings_currency",
        ),
        CheckConstraint(
            "pricing_unit IS NULL OR pricing_unit = 'million_tokens'",
            name="ck_provider_model_catalog_mappings_unit",
        ),
        Index(
            "uq_provider_model_catalog_mappings_primary_active",
            "provider_model_offering_id",
            unique=True,
            sqlite_where=text("is_active = 1 AND is_primary = 1"),
            postgresql_where=text("is_active = true AND is_primary = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
    )
    provider_model_offering_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_model_offerings.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_catalog_entries.id", ondelete="RESTRICT"),
        index=True,
    )
    match_source: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[str] = mapped_column(String(50))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    input_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_price_per_million_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_price_per_million_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pricing_currency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pricing_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pricing_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pricing_last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
