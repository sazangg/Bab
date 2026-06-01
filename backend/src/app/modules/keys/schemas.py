from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    team_id: UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateVirtualKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None
    allowed_models: list[str] | None = None

    @field_validator("allowed_models")
    @classmethod
    def reject_empty_model_list(cls, value: list[str] | None) -> list[str] | None:
        if value == []:
            raise ValueError("allowed_models must be null or contain at least one model")
        return value


class UpdateVirtualKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None
    allowed_models: list[str] | None = None


class VirtualKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    key_prefix: str
    allowed_models: list[str] | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreatedVirtualKeyResponse(VirtualKeyResponse):
    key: str | None


class ResolveAccessRequest(BaseModel):
    raw_key: str = Field(min_length=1)
    requested_model: str = Field(min_length=1, max_length=255)


class ResolvedLimitPolicy(BaseModel):
    limit_policy_id: UUID
    limit_policy_rule_id: UUID
    name: str
    budget_cents: int | None
    max_requests: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_tokens_per_request: int | None
    window: str


class ResolvedAccess(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    access_policy_id: UUID
    access_policy_route_id: UUID
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


class AccessibleModel(BaseModel):
    id: str
    object: str = "model"
    owned_by: str
    provider_id: UUID
    access_policy_id: UUID | None = None
    access_policy_route_id: UUID | None = None
    pool_id: UUID
    alias: str | None = None
