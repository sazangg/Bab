from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ValidatedScope:
    scope_type: str
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
