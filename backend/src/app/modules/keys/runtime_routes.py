from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.keys.schemas import ResolvedAccessPlan


@dataclass(frozen=True, slots=True)
class RuntimeRouteContext:
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    requested_model: str
    gateway_endpoint: str
    streaming: bool
    public_model_id: UUID | None
    public_model_name: str | None
    routing_mode: str | None
    access_policy_id: UUID | None
    access_policy_revision_id: UUID | None
    access_policy_assignment_id: UUID | None
    route_candidate_id: UUID | None
    candidate_index: int
    attempt_index: int | None
    provider_id: UUID | None
    provider_name: str | None
    credential_pool_id: UUID | None
    credential_pool_name: str | None
    provider_model_offering_id: UUID | None
    provider_model: str | None
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None
    cached_input_price_per_million_tokens: int | None = None
    capability_snapshot: dict[str, Any] = field(default_factory=dict)
    route_snapshot: dict[str, Any] = field(default_factory=dict)
    draft_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RouteCandidateExplanation:
    candidate_index: int
    route_candidate_id: UUID | None = None
    public_model_id: UUID | None = None
    public_model_name: str | None = None
    access_policy_id: UUID | None = None
    access_policy_revision_id: UUID | None = None
    assignment_id: UUID | None = None
    provider_id: UUID | None = None
    provider_name: str | None = None
    credential_pool_id: UUID | None = None
    credential_pool_name: str | None = None
    provider_model_offering_id: UUID | None = None
    provider_model: str | None = None
    attempt_index: int | None = None
    selected: bool = False
    would_attempt: bool = False
    skipped_reason: str | None = None
    skipped_message: str | None = None
    draft_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAccessPlanExplanation:
    plan: ResolvedAccessPlan | None
    candidates: list[RouteCandidateExplanation]
    access_denied_reason: str | None = None
