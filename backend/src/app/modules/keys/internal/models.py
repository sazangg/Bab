import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"),
        index=True,
    )
    created_by: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
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


class ProjectAllocation(Base):
    __tablename__ = "project_allocations"
    __table_args__ = (UniqueConstraint("project_id", "provider_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"),
        index=True,
    )
    model_offering_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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


class ModelAlias(Base):
    __tablename__ = "model_aliases"
    __table_args__ = (UniqueConstraint("org_id", "alias"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(255))
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_model: Mapped[str] = mapped_column(String(255))
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


class VirtualKey(Base):
    __tablename__ = "virtual_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(32), index=True)
    restrictions: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
