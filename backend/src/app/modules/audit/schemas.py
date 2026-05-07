from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecordAuditEvent(BaseModel):
    org_id: UUID
    actor_user_id: UUID | None = None
    event: str = Field(min_length=1, max_length=100)
    target_type: str | None = Field(default=None, max_length=100)
    target_id: UUID | None = None
    ip_address: str | None = Field(default=None, max_length=100)
    user_agent: str | None = Field(default=None, max_length=500)
    event_metadata: dict | None = None


class AuditEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    actor_user_id: UUID | None
    event: str
    target_type: str | None
    target_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    event_metadata: dict | None
    created_at: datetime
