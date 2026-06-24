from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class SimulationAssignmentContext(Protocol):
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None


class SimulationTargetContext(Protocol):
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID


class SimulationRouteContext(Protocol):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    model_offering_id: UUID
    public_model_id: UUID | None
    public_model_name: str | None
    route_candidate_id: UUID | None
    provider_model: str


@dataclass(frozen=True)
class SimulationReplacementPolicy:
    concrete_id: UUID
    shared_policy_id: UUID
