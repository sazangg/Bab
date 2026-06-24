from typing import Protocol
from uuid import UUID


class GuardrailResolvedAccess(Protocol):
    org_id: UUID
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    model_offering_id: UUID
    public_model_id: UUID | None
    public_model_name: str | None
    route_candidate_id: UUID | None
    requested_model: str
    provider_model: str
