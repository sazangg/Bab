from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecordActivityEvent(BaseModel):
    org_id: UUID
    category: str = Field(max_length=50)
    severity: str = Field(default="info", max_length=50)
    action: str = Field(max_length=100)
    message: str = Field(max_length=500)
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    team_id: UUID | None = None
    project_id: UUID | None = None
    allocation_id: UUID | None = None
    virtual_key_id: UUID | None = None
    provider_id: UUID | None = None
    pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)


class ActivityEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    category: str
    severity: str
    action: str
    message: str
    actor_user_id: UUID | None
    actor_email: str | None
    team_id: UUID | None
    project_id: UUID | None
    allocation_id: UUID | None
    virtual_key_id: UUID | None
    provider_id: UUID | None
    pool_id: UUID | None
    model_offering_id: UUID | None
    metadata: dict
    created_at: datetime
