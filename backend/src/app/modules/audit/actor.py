from typing import Protocol
from uuid import UUID


class AuditActor(Protocol):
    id: UUID
    org_id: UUID
    email: object
    role: str
