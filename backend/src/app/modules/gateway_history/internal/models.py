import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GatewayRequest(Base):
    __tablename__ = "gateway_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    virtual_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("virtual_keys.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    gateway_endpoint: Mapped[str] = mapped_column(String(50))
    requested_model: Mapped[str] = mapped_column(String(255))
    public_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_public_models.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    public_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    routing_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    final_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    final_public_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_public_models.id", ondelete="RESTRICT"),
        nullable=True,
    )
    final_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_route_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    final_route_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "gateway_route_attempts.id",
            name="fk_gateway_requests_final_route_attempt_id_gateway_route_attempts",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    final_provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    final_credential_pool_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        nullable=True,
    )
    final_model_offering_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_model_offerings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    final_provider_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    final_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    trace_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GatewayRouteAttempt(Base):
    __tablename__ = "gateway_route_attempts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        index=True,
    )
    gateway_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("gateway_requests.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_index: Mapped[int] = mapped_column(Integer)
    access_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    access_policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    access_public_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_public_models.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    route_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_route_candidates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    primary_route_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_route_candidates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential_pool_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credential_pools.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    credential_pool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider_credential_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_credential_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_model_offering_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_model_offerings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_from_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gateway_route_attempts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    fallback_trigger_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skipped_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="planned", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(50), default="unknown")
    pricing_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    capability_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    route_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GatewayPolicyDecision(Base):
    __tablename__ = "gateway_policy_decisions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    gateway_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("gateway_requests.id", ondelete="CASCADE"),
        index=True,
    )
    route_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gateway_route_attempts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    decision_type: Mapped[str] = mapped_column(String(50), index=True)
    stage: Mapped[str] = mapped_column(String(50), index=True)
    outcome: Mapped[str] = mapped_column(String(50), index=True)
    effective_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enforced: Mapped[bool] = mapped_column(Boolean, default=True)
    policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_assignments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assignment_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignment_scope_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignment_team_id: Mapped[UUID | None] = mapped_column(nullable=True)
    assignment_project_id: Mapped[UUID | None] = mapped_column(nullable=True)
    assignment_virtual_key_id: Mapped[UUID | None] = mapped_column(nullable=True)
    rule_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    route_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policy_route_candidates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    dimension_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
