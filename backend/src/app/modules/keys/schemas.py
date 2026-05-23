from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class AllocationOffering(BaseModel):
    pool_id: UUID
    model_offering_id: UUID


class CreateAllocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    parent_allocation_id: UUID | None = None
    team_id: UUID | None = None
    project_id: UUID | None = None
    offerings: list[AllocationOffering] = Field(min_length=1)
    is_default: bool = True
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str = Field(default="monthly", pattern="^(daily|weekly|monthly|lifetime)$")

    @model_validator(mode="after")
    def require_one_target(self):
        if (self.team_id is None) == (self.project_id is None):
            raise ValueError("exactly one of team_id or project_id is required")
        return self


class UpdateAllocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    offerings: list[AllocationOffering] | None = None
    is_default: bool | None = None
    budget_cents: int | None = Field(default=None, ge=0)
    max_requests: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_tokens_per_request: int | None = Field(default=None, ge=1)
    window: str | None = Field(default=None, pattern="^(daily|weekly|monthly|lifetime)$")
    is_active: bool | None = None

    @field_validator("offerings")
    @classmethod
    def reject_empty_offerings(cls, value: list[AllocationOffering] | None):
        if value == []:
            raise ValueError("offerings must contain at least one entry")
        return value


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    parent_allocation_id: UUID | None
    target_type: str
    team_id: UUID | None
    project_id: UUID | None
    name: str
    description: str | None
    offerings: list[AllocationOffering]
    is_default: bool
    budget_cents: int | None
    max_requests: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_tokens_per_request: int | None
    window: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateVirtualKeyRequest(BaseModel):
    allocation_id: UUID | None = None
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
    custom_allocation_id: UUID | None = None


class VirtualKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    allocation_id: UUID
    custom_allocation_id: UUID | None
    allocation_mode: str
    name: str
    key_prefix: str
    allowed_models: list[str] | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreatedVirtualKeyResponse(VirtualKeyResponse):
    key: str


class ResolveAccessRequest(BaseModel):
    raw_key: str = Field(min_length=1)
    requested_model: str = Field(min_length=1, max_length=255)


class ResolvedAllocationLimit(BaseModel):
    allocation_id: UUID
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
    allocation_id: UUID
    allocation_chain_ids: list[UUID]
    allocation_limits: list[ResolvedAllocationLimit]
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None = None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
