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
