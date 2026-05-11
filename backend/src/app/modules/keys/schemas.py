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
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GrantProjectProviderAccessRequest(BaseModel):
    provider_id: UUID
    allowed_models: list[str] | None = None

    @field_validator("allowed_models")
    @classmethod
    def reject_empty_model_list(cls, value: list[str] | None) -> list[str] | None:
        if value == []:
            raise ValueError(
                "allowed_models must be null for all models or contain at least one model"
            )
        return value


class UpdateProjectProviderAccessRequest(BaseModel):
    allowed_models: list[str] | None = None

    @field_validator("allowed_models")
    @classmethod
    def reject_empty_model_list(cls, value: list[str] | None) -> list[str] | None:
        if value == []:
            raise ValueError(
                "allowed_models must be null for all models or contain at least one model"
            )
        return value


class ProjectProviderAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    provider_id: UUID
    allowed_models: list[str] | None
    created_at: datetime
    updated_at: datetime


class CreateSubscriptionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class UpdateSubscriptionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AttachSubscriptionProviderKeyRequest(BaseModel):
    provider_key_id: UUID
    priority: int = Field(default=100, ge=0)


class SubscriptionProviderKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    subscription_id: UUID
    provider_key_id: UUID
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SetSubscriptionModelAccessRequest(BaseModel):
    provider_model_ids: list[UUID] | None = None

    @field_validator("provider_model_ids")
    @classmethod
    def reject_empty_model_list(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value == []:
            raise ValueError(
                "provider_model_ids must be null for all models or contain at least one model"
            )
        return value


class SubscriptionModelAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    subscription_id: UUID
    provider_model_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GrantProjectSubscriptionAccessRequest(BaseModel):
    subscription_id: UUID
    priority: int = Field(default=100, ge=0)


class ProjectSubscriptionAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    subscription_id: UUID
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateModelAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=255)
    provider_id: UUID
    provider_model: str = Field(min_length=1, max_length=255)


class UpdateModelAliasRequest(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    provider_id: UUID | None = None
    provider_model: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class ModelAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    alias: str
    provider_id: UUID
    provider_model: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VirtualKeyRestriction(BaseModel):
    provider_id: UUID
    allowed_models: list[str] | None = None

    @field_validator("allowed_models")
    @classmethod
    def reject_empty_model_list(cls, value: list[str] | None) -> list[str] | None:
        if value == []:
            raise ValueError(
                "allowed_models must be null for all models or contain at least one model"
            )
        return value


class CreateVirtualKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None
    restrictions: list[VirtualKeyRestriction] | None = None


class UpdateVirtualKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None
    restrictions: list[VirtualKeyRestriction] | None = None


class VirtualKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    key_prefix: str
    restrictions: list[VirtualKeyRestriction] | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreatedVirtualKeyResponse(VirtualKeyResponse):
    key: str


class ResolveAccessRequest(BaseModel):
    raw_key: str = Field(min_length=1)
    requested_model: str = Field(min_length=1, max_length=255)
    provider: str | None = Field(default=None, min_length=1, max_length=100)
    provider_id: UUID | None = None


class ResolvedAccess(BaseModel):
    org_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    requested_model: str
    provider_model: str
    used_alias: bool
