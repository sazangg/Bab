from typing import Protocol
from uuid import UUID


class WorkspaceActor(Protocol):
    id: UUID
    org_id: UUID
    email: str
    role: str
