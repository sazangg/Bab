import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    organization_name: Mapped[str] = mapped_column(String(255))
    organization_logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    public_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    default_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    default_max_body_bytes: Mapped[int] = mapped_column(Integer)
    default_model_sync_mode: Mapped[str] = mapped_column(String(50), default="merge")
    default_virtual_key_expiration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    virtual_key_prefix: Mapped[str] = mapped_column(String(32), default="bab")
    allow_secret_copy: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
