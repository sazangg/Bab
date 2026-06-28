from uuid import UUID

from pydantic import BaseModel, Field


class OwnershipChainState(BaseModel):
    organization_active: bool
    team_active: bool
    project_active: bool
    key_active: bool | None = None


class EffectivePolicyReference(BaseModel):
    id: UUID
    name: str
    source_scope: str


class EffectiveRouteSummary(BaseModel):
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_id: UUID
    public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None
    provider_model: str
    access_policy_id: UUID | None = None
    access_policy_revision_id: UUID | None = None
    access_policy_name: str | None = None
    access_policy_assignment_id: UUID | None = None
    source_scope: str | None = None


class EffectiveLimitReference(BaseModel):
    id: UUID
    name: str
    source_scope: str


class EffectiveAccessSummary(BaseModel):
    is_usable: bool
    blocking_code: str | None
    blocking_reason: str | None
    ownership: OwnershipChainState
    access_policy: EffectivePolicyReference | None
    access_policies: list[EffectivePolicyReference] = Field(default_factory=list)
    routes: list[EffectiveRouteSummary]
    limit_policies: list[EffectiveLimitReference]
