from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.usage.schemas import UsageRecordResponse


@dataclass(frozen=True)
class GatewayRequestResolvedSubject:
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID


class CreateGatewayRequest(BaseModel):
    org_id: UUID | None = None
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    request_id: str | None = None
    gateway_endpoint: str
    requested_model: str
    public_model_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None


class FinalizeGatewayRequest(BaseModel):
    final_http_status: int
    final_access_policy_id: UUID | None = None
    final_public_model_id: UUID | None = None
    final_candidate_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    final_provider_id: UUID | None = None
    final_credential_pool_id: UUID | None = None
    final_model_offering_id: UUID | None = None
    final_provider_model: str | None = None
    attempt_count: int
    fallback_attempted: bool = False
    final_error_code: str | None = None


class GatewayRequestTraceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    request_id: str | None = None
    gateway_endpoint: str
    requested_model: str
    public_model_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None
    final_http_status: int | None = None
    final_access_policy_id: UUID | None = None
    final_public_model_id: UUID | None = None
    final_candidate_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    final_provider_id: UUID | None = None
    final_credential_pool_id: UUID | None = None
    final_model_offering_id: UUID | None = None
    final_provider_model: str | None = None
    attempt_count: int
    fallback_attempted: bool
    final_error_code: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    trace_expires_at: datetime


class GatewayRouteAttemptTrace(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    gateway_request_id: UUID
    attempt_index: int
    access_policy_id: UUID | None = None
    access_policy_revision_id: UUID | None = None
    access_public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    primary_route_candidate_id: UUID | None = None
    provider_id: UUID | None = None
    provider_name: str | None = None
    provider_slug: str | None = None
    credential_pool_id: UUID | None = None
    credential_pool_name: str | None = None
    provider_credential_id: UUID | None = None
    provider_credential_name: str | None = None
    provider_credential_prefix: str | None = None
    provider_model_offering_id: UUID | None = None
    provider_model: str | None = None
    public_model_name: str | None = None
    fallback_from_attempt_id: UUID | None = None
    fallback_trigger_reason: str | None = None
    skipped_reason: str | None = None
    status: str
    http_status: int | None = None
    error_code: str | None = None
    failure_reason: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_cents: int | None = None
    cost_micro_cents: int | None = None
    usage_source: str
    pricing_snapshot: dict
    capability_snapshot: dict
    route_snapshot: dict
    started_at: datetime
    completed_at: datetime | None = None


class GatewayPolicyDecisionTrace(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    gateway_request_id: UUID
    route_attempt_id: UUID | None = None
    decision_type: str
    stage: str
    outcome: str
    effective_action: str | None = None
    enforced: bool
    policy_id: UUID | None = None
    policy_revision_id: UUID | None = None
    assignment_id: UUID | None = None
    assignment_mode: str | None = None
    assignment_scope_type: str | None = None
    assignment_team_id: UUID | None = None
    assignment_project_id: UUID | None = None
    assignment_virtual_key_id: UUID | None = None
    rule_id: UUID | None = None
    route_candidate_id: UUID | None = None
    reason_code: str | None = None
    message: str | None = None
    dimension_snapshot: dict
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime


class GuardrailEventTrace(BaseModel):
    id: UUID
    org_id: UUID
    policy_id: UUID | None
    policy_revision_id: UUID | None
    rule_id: UUID | None
    decision: str
    phase: str
    reason: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    provider_id: UUID | None
    pool_id: UUID | None
    request_id: str | None
    gateway_request_id: UUID | None
    route_attempt_id: UUID | None
    requested_model: str | None
    provider_model: str | None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class GatewayTraceTimelineItem(BaseModel):
    timestamp: datetime
    kind: Literal[
        "request",
        "route_attempt",
        "policy_decision",
        "guardrail_event",
        "usage_record",
    ]
    title: str
    status: str | None = None
    stage: str | None = None
    route_attempt_id: UUID | None = None
    policy_decision_id: UUID | None = None
    guardrail_event_id: UUID | None = None
    usage_record_id: UUID | None = None
    severity: Literal["info", "success", "warning", "error"] = "info"
    summary: str | None = None
    metadata: dict = Field(default_factory=dict)


class GatewayRequestTraceResponse(BaseModel):
    request: GatewayRequestTraceSummary
    timeline: list[GatewayTraceTimelineItem] = Field(default_factory=list)
    route_attempts: list[GatewayRouteAttemptTrace] = Field(default_factory=list)
    policy_decisions: list[GatewayPolicyDecisionTrace] = Field(default_factory=list)
    guardrail_events: list[GuardrailEventTrace] = Field(default_factory=list)
    usage_records: list[UsageRecordResponse] = Field(default_factory=list)


class GatewayRequestTraceListItem(BaseModel):
    id: UUID
    org_id: UUID | None = None
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    request_id: str | None = None
    gateway_endpoint: str
    requested_model: str
    public_model_name: str | None = None
    routing_mode: str | None = None
    final_http_status: int | None = None
    final_provider_id: UUID | None = None
    final_provider_name: str | None = None
    final_credential_pool_id: UUID | None = None
    final_credential_pool_name: str | None = None
    final_provider_model: str | None = None
    final_access_policy_id: UUID | None = None
    final_access_policy_name: str | None = None
    team_name: str | None = None
    project_name: str | None = None
    virtual_key_name: str | None = None
    involved_provider_ids: list[UUID] = Field(default_factory=list)
    involved_provider_names: list[str] = Field(default_factory=list)
    attempt_count: int
    fallback_attempted: bool
    final_error_code: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    trace_expires_at: datetime
    outcome: Literal["succeeded", "failed", "denied", "pending"]
    duration_ms: int | None = None


class GatewayRequestTraceListResponse(BaseModel):
    items: list[GatewayRequestTraceListItem]
    limit: int
    offset: int
    has_more: bool
