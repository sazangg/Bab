from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LimitEvaluationContext(BaseModel):
    org_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    provider_model: str = Field(min_length=1, max_length=255)


class LimitPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    scope_type: str
    scope_id: UUID | None
    scope_value: str | None
    metric: str
    window: str
    limit_value: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateLimitPolicyRequest(BaseModel):
    scope_type: str = Field(max_length=50)
    scope_id: UUID | None = None
    scope_value: str | None = Field(default=None, max_length=255)
    metric: str = Field(max_length=50)
    window: str = Field(max_length=20)
    limit_value: int = Field(gt=0)


class UpdateLimitPolicyRequest(BaseModel):
    scope_type: str | None = Field(default=None, max_length=50)
    scope_id: UUID | None = None
    scope_value: str | None = Field(default=None, max_length=255)
    metric: str | None = Field(default=None, max_length=50)
    window: str | None = Field(default=None, max_length=20)
    limit_value: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
