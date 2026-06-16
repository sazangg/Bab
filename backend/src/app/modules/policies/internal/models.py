import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
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
    owning_scope_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    owning_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owning_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owning_virtual_key_id: Mapped[UUID | None] = mapped_column(
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


class AccessPolicyPublicModel(Base):
    __tablename__ = "access_policy_public_models"
    __table_args__ = (
        UniqueConstraint(
            "access_policy_id",
            "public_model_name",
            name="uq_access_policy_public_models_policy_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    access_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"),
        index=True,
    )
    public_model_name: Mapped[str] = mapped_column(String(255), index=True)
    routing_mode: Mapped[str] = mapped_column(String(50), default="single_route")
    fallback_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_route_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class AccessPolicyRouteCandidate(Base):
    __tablename__ = "access_policy_route_candidates"
    __table_args__ = (
        UniqueConstraint(
            "public_model_id",
            "provider_id",
            "credential_pool_id",
            "model_offering_id",
            name="uq_access_policy_route_candidates_route",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    public_model_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_policy_public_models.id", ondelete="CASCADE"),
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
    model_offering_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_offerings.id", ondelete="RESTRICT"),
        index=True,
    )
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
    owning_scope_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    owning_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owning_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owning_virtual_key_id: Mapped[UUID | None] = mapped_column(
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
    limit_type: Mapped[str] = mapped_column(String(50))
    limit_value: Mapped[int] = mapped_column(Integer)
    interval_unit: Mapped[str] = mapped_column(String(50), default="month")
    interval_count: Mapped[int] = mapped_column(Integer, default=1)
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
