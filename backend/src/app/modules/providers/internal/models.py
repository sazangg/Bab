import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Provider(Base):
    __tablename__ = "providers"

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
    fallback_policy: Mapped[dict] = mapped_column(JSON, default=dict)
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
    api_key_encrypted: Mapped[str] = mapped_column(String(1000))
    health_status: Mapped[str] = mapped_column(String(50), default="unchecked")
    last_validation_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_successful_request_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    __tablename__ = "model_offerings"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_model_name",
            name="uq_model_offering_provider_name",
        ),
        UniqueConstraint("provider_id", "alias", name="uq_model_offering_provider_alias"),
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
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
