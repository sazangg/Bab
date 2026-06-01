import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AccessPolicy(Base):
    __tablename__ = "access_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
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


class AccessPolicyRoute(Base):
    __tablename__ = "access_policy_routes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    access_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        index=True,
    )
    credential_pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        index=True,
    )
    model_offering_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    weight: Mapped[int] = mapped_column(Integer, default=100)
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


class LimitPolicy(Base):
    __tablename__ = "limit_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens_per_request: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window: Mapped[str] = mapped_column(String(50), default="monthly")
    provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    credential_pool_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    model_offering_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_offerings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
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


class LimitPolicyRule(Base):
    __tablename__ = "limit_policy_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    limit_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("limit_policies.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens_per_request: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window: Mapped[str] = mapped_column(String(50), default="monthly")
    provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    credential_pool_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    model_offering_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_offerings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
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


class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_type: Mapped[str] = mapped_column(String(20), index=True)
    access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    limit_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("limit_policies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    virtual_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("virtual_keys.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
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
