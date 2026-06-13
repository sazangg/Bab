import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"),
        index=True,
    )
    access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    access_policy_route_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_routes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    limit_policy_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    limit_policy_rule_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    limit_policy_assignment_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    virtual_key_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_keys.id", ondelete="RESTRICT"),
        index=True,
    )
    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    requested_model: Mapped[str] = mapped_column(String(255))
    provider_model: Mapped[str] = mapped_column(String(255))
    http_status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Exact cost in micro-cents (1_000_000 == 1 cent); cost_cents is the rounded
    # display value. Budget enforcement sums this to avoid per-request rounding drift.
    cost_micro_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(50), default="unknown")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )


class LimitPolicyReservation(Base):
    __tablename__ = "limit_policy_reservations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    limit_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("limit_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    limit_policy_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("limit_policy_rules.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    limit_policy_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_assignments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    virtual_key_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_keys.id", ondelete="RESTRICT"),
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    reserved_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_cost_micro_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_micro_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
