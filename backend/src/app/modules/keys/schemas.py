from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.policy_kernel.effective_access_schemas import (
    EffectiveAccessSummary as EffectiveAccessSummary,
)
from app.modules.policy_kernel.effective_access_schemas import (
    EffectiveLimitReference as EffectiveLimitReference,
)
from app.modules.policy_kernel.effective_access_schemas import (
    EffectivePolicyReference as EffectivePolicyReference,
)
from app.modules.policy_kernel.effective_access_schemas import (
    EffectiveRouteSummary as EffectiveRouteSummary,
)
from app.modules.policy_kernel.effective_access_schemas import (
    OwnershipChainState as OwnershipChainState,
)


class CreateVirtualKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class UpdateVirtualKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None


class RevokeVirtualKeyRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    force: bool = False

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("revocation reason must not be empty")
        return reason


class RotateVirtualKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None
    overlap_days: int = Field(default=7, ge=1, le=90)


class VirtualKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    supersedes_key_id: UUID | None
    name: str
    key_prefix: str
    status: str
    is_usable: bool
    created_by: UUID | None
    creator_name: str | None
    creator_email: str | None
    last_used_at: datetime | None
    expires_at: datetime | None
    deprecated_at: datetime | None
    revoked_at: datetime | None
    revoked_by: UUID | None
    revoker_name: str | None
    revoker_email: str | None
    revoked_reason: str | None
    created_at: datetime
    updated_at: datetime


class VirtualKeyIdentity(BaseModel):
    id: UUID
    org_id: UUID
    project_id: UUID


class VirtualKeyOption(BaseModel):
    id: UUID
    name: str
    project_id: UUID
    project_name: str


class VirtualKeyTarget(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    virtual_key_name: str | None


class CreatedVirtualKeyResponse(VirtualKeyResponse):
    key: str | None


class VirtualKeyInventoryItem(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    project_id: UUID
    supersedes_key_id: UUID | None
    project_name: str
    project_is_active: bool
    team_id: UUID
    team_name: str
    team_is_active: bool
    status: str
    is_usable: bool
    can_manage: bool
    created_by: UUID | None
    creator_name: str | None
    creator_email: str | None
    created_at: datetime
    expires_at: datetime | None
    deprecated_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    revoked_by: UUID | None
    revoked_reason: str | None


class VirtualKeyInventoryPage(BaseModel):
    items: list[VirtualKeyInventoryItem]
    total: int
    limit: int
    offset: int


class VirtualKeyRevokeImpactResponse(BaseModel):
    last_used_at: datetime | None = None
    recent_usage_window_days: int = 30
    recent_request_count: int = 0
    recent_cost_cents: int = 0
    effective_access: EffectiveAccessSummary
    already_unusable_reason: str | None = None


class ResolveAccessRequest(BaseModel):
    raw_key: str = Field(min_length=1)
    requested_model: str = Field(min_length=1, max_length=255)
    provider_id: UUID | None = None
    streaming: bool = False
    gateway_endpoint: str | None = None


class ResolveKeySubjectRequest(BaseModel):
    raw_key: str = Field(min_length=1)


class ResolvedKeySubject(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    virtual_key_name: str | None = None
    project_name: str | None = None
    team_name: str | None = None


class ResolveAccessPlanForSubjectRequest(BaseModel):
    subject: ResolvedKeySubject
    requested_model: str = Field(min_length=1, max_length=255)
    gateway_endpoint: str | None = None
    streaming: bool = False
    provider_id: UUID | None = None


class ResolveAccessPlanForVirtualKeyRequest(BaseModel):
    virtual_key_id: UUID
    requested_model: str = Field(min_length=1, max_length=255)
    gateway_endpoint: str | None = None
    streaming: bool = False
    provider_id: UUID | None = None


class ResolvedLimitPolicy(BaseModel):
    limit_policy_assignment_id: UUID | None
    limit_policy_id: UUID | None
    limit_policy_revision_id: UUID | None = None
    limit_policy_name: str
    limit_policy_rule_id: UUID | None
    name: str
    limit_type: str
    limit_value: int
    interval_unit: str
    interval_count: int
    matchers: list[dict[str, Any]] = Field(default_factory=list)
    partitions: list[dict[str, Any]] = Field(default_factory=list)
    draft_ref: str | None = None


class ResolvedAccess(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    access_policy_id: UUID
    access_policy_revision_id: UUID | None = None
    access_policy_assignment_id: UUID | None = None
    access_policy_route_id: UUID | None
    public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    primary_route_candidate_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None
    model_offering_id: UUID
    limit_policy_ids: list[UUID]
    limit_policies: list[ResolvedLimitPolicy]
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None = None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
    fallback_disabled_reason: str | None = None


class ResolvedRouteAttempt(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    access_policy_id: UUID
    access_policy_revision_id: UUID | None = None
    access_policy_assignment_id: UUID | None = None
    access_policy_route_id: UUID | None
    public_model_id: UUID
    route_candidate_id: UUID
    public_model_name: str
    routing_mode: str
    model_offering_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None = None
    requested_model: str
    provider_model: str
    routing_attempt_index: int
    primary_route_candidate_id: UUID
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
    limit_policy_ids: list[UUID] = Field(default_factory=list)
    limit_policies: list[ResolvedLimitPolicy] = Field(default_factory=list)


class ResolvedAccessPlan(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    requested_model: str
    public_model_name: str
    routing_mode: str
    fallback_on: list[str] = Field(default_factory=list)
    max_route_attempts: int | None = None
    provider_pinned: bool = False
    fallback_disabled_reason: str | None = None
    limit_policy_ids: list[UUID]
    limit_policies: list[ResolvedLimitPolicy]
    attempts: list[ResolvedRouteAttempt]


class AccessibleModelCandidate(BaseModel):
    provider_id: UUID
    provider_name: str
    pool_id: UUID
    pool_name: str
    model_offering_id: UUID
    provider_model: str
    route_candidate_id: UUID | None = None
    access_policy_route_id: UUID | None = None
    priority: int
    weight: int


class AccessibleModel(BaseModel):
    id: str
    object: str = "model"
    owned_by: str
    provider_id: UUID
    provider_name: str
    model_offering_id: UUID
    access_policy_id: UUID | None = None
    access_policy_name: str | None = None
    access_policy_route_id: UUID | None = None
    public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None
    pool_id: UUID
    pool_name: str
    source_scope: str | None = None
    candidates: list[AccessibleModelCandidate] = Field(default_factory=list)
