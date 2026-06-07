from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccessPolicyRouteInput(BaseModel):
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_ids: list[UUID] = Field(min_length=1)
    priority: int = Field(default=100, ge=1)
    weight: int = Field(default=100, ge=1)
    is_active: bool = True


class CreateAccessPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    routes: list[AccessPolicyRouteInput] = Field(default_factory=list)
    is_active: bool = True


class UpdateAccessPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class CreateAccessPolicyRouteRequest(AccessPolicyRouteInput):
    pass


class UpdateAccessPolicyRouteRequest(BaseModel):
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_ids: list[UUID] | None = Field(default=None, min_length=1)
    priority: int | None = Field(default=None, ge=1)
    weight: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class AccessPolicyRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    access_policy_id: UUID
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_ids: list[UUID]
    priority: int
    weight: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccessPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    routes: list[AccessPolicyRouteResponse] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccessPolicyModelOption(BaseModel):
    id: UUID
    provider_model_name: str
    alias: str | None = None


class AccessPolicyPoolOption(BaseModel):
    id: UUID
    name: str
    models: list[AccessPolicyModelOption] = Field(default_factory=list)


class AccessPolicyProviderOption(BaseModel):
    id: UUID
    display_name: str
    pools: list[AccessPolicyPoolOption] = Field(default_factory=list)


class AccessPolicyOptionsResponse(BaseModel):
    providers: list[AccessPolicyProviderOption] = Field(default_factory=list)


class CreateLimitPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    rules: list["LimitPolicyRuleInput"] = Field(default_factory=list)
    is_active: bool = True


class LimitPolicyRuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    limit_type: str = Field(
        pattern="^(budget_cents|requests|input_tokens|output_tokens|total_tokens|tokens_per_request)$"
    )
    limit_value: int = Field(ge=1)
    interval_unit: str = Field(default="month", pattern="^(minute|hour|day|week|month|lifetime)$")
    interval_count: int = Field(default=1, ge=1)
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    is_active: bool = True


class UpdateLimitPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class CreateLimitPolicyRuleRequest(LimitPolicyRuleInput):
    pass


class UpdateLimitPolicyRuleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    limit_type: str | None = Field(
        default=None,
        pattern="^(budget_cents|requests|input_tokens|output_tokens|total_tokens|tokens_per_request)$",
    )
    limit_value: int | None = Field(default=None, ge=1)
    interval_unit: str | None = Field(
        default=None, pattern="^(minute|hour|day|week|month|lifetime)$"
    )
    interval_count: int | None = Field(default=None, ge=1)
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    is_active: bool | None = None


class LimitPolicyRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    limit_policy_id: UUID
    name: str
    limit_type: str
    limit_value: int
    interval_unit: str
    interval_count: int
    provider_id: UUID | None
    credential_pool_id: UUID | None
    model_offering_id: UUID | None
    access_policy_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LimitPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    rules: list[LimitPolicyRuleResponse] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreatePolicyAssignmentRequest(BaseModel):
    policy_type: str = Field(pattern="^(access|limit)$")
    access_policy_id: UUID | None = None
    limit_policy_id: UUID | None = None
    scope_type: str = Field(pattern="^(org|team|project|virtual_key)$")
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_assignment(self):
        if self.policy_type == "access" and self.access_policy_id is None:
            raise ValueError("access_policy_id is required for access assignments")
        if self.policy_type == "limit" and self.limit_policy_id is None:
            raise ValueError("limit_policy_id is required for limit assignments")
        expected_scope_id = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected_scope_id is None:
            raise ValueError(f"{self.scope_type}_id is required for this scope")
        return self


class UpdatePolicyAssignmentRequest(BaseModel):
    is_active: bool | None = None


class PolicyAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_type: str
    access_policy_id: UUID | None
    limit_policy_id: UUID | None
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PolicyImpactTarget(BaseModel):
    id: UUID
    name: str


class PolicyImpactVirtualKey(PolicyImpactTarget):
    project_id: UUID
    project_name: str


class PolicyImpactResponse(BaseModel):
    affected_teams: list[PolicyImpactTarget] = Field(default_factory=list)
    affected_projects: list[PolicyImpactTarget] = Field(default_factory=list)
    affected_virtual_keys: list[PolicyImpactVirtualKey] = Field(default_factory=list)
    affected_team_count: int = 0
    affected_project_count: int = 0
    affected_virtual_key_count: int = 0
    virtual_keys_would_become_unusable: list[PolicyImpactVirtualKey] = Field(default_factory=list)
    virtual_keys_would_become_unusable_count: int = 0
