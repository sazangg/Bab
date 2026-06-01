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


class CreateLimitPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    rules: list["LimitPolicyRuleInput"] = Field(default_factory=list)
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str = Field(default="monthly", pattern="^(daily|weekly|monthly|lifetime)$")
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    is_active: bool = True


class LimitPolicyRuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str = Field(default="monthly", pattern="^(daily|weekly|monthly|lifetime)$")
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    is_active: bool = True


class UpdateLimitPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str | None = Field(default=None, pattern="^(daily|weekly|monthly|lifetime)$")
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    is_active: bool | None = None


class CreateLimitPolicyRuleRequest(LimitPolicyRuleInput):
    pass


class UpdateLimitPolicyRuleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str | None = Field(default=None, pattern="^(daily|weekly|monthly|lifetime)$")
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
    budget_cents: int | None
    max_requests: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_tokens_per_request: int | None
    window: str
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
    budget_cents: int | None
    max_requests: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_tokens_per_request: int | None
    window: str
    provider_id: UUID | None
    credential_pool_id: UUID | None
    model_offering_id: UUID | None
    access_policy_id: UUID | None
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
