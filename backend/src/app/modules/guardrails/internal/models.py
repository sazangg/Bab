import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GuardrailPolicy(Base):
    __tablename__ = "guardrail_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    enforcement_mode: Mapped[str] = mapped_column(String(50), default="enforce", index=True)
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


class GuardrailRule(Base):
    __tablename__ = "guardrail_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("guardrail_policies.id", ondelete="CASCADE"),
        index=True,
    )
    policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    rule_type: Mapped[str] = mapped_column(String(50), index=True)
    effect: Mapped[str] = mapped_column(String(50), default="allow", index=True)
    phase: Mapped[str] = mapped_column(String(50), default="both", index=True)
    values: Mapped[list[str]] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=100)
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


class GuardrailRuleMatcher(Base):
    __tablename__ = "guardrail_rule_matchers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("guardrail_rules.id", ondelete="CASCADE"),
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(100), index=True)
    operator: Mapped[str] = mapped_column(String(50))
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class GuardrailAssignment(Base):
    __tablename__ = "guardrail_assignments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("guardrail_policies.id", ondelete="CASCADE"),
        index=True,
    )
    policy_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(50), index=True)
    team_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    virtual_key_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    enforcement_mode: Mapped[str] = mapped_column(String(50), default="enforce", index=True)
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


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"
    __table_args__ = (
        CheckConstraint(
            "decision in ('allowed', 'blocked', 'would_allow', 'would_block')",
            name="ck_guardrail_events_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    rule_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(50), index=True)
    phase: Mapped[str] = mapped_column(String(50), default="request", index=True)
    reason: Mapped[str] = mapped_column(String(255))
    team_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    virtual_key_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    provider_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    gateway_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gateway_requests.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    route_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gateway_route_attempts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    requested_model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
