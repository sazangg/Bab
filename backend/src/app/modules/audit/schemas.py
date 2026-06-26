from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    org_id: UUID
    actor_user_id: UUID | None
    actor_email: str | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: UUID | None
    metadata: dict
    previous_hash: str | None
    event_hash: str | None
    signature_algorithm: str
    created_at: datetime


class AuditVerificationResponse(BaseModel):
    valid: bool
    checked_events: int
    first_invalid_event_id: UUID | None = None
    reason: str | None = None
