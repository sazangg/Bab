from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ValidatedScope:
    scope_type: str
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None


@dataclass(frozen=True)
class WorkspaceTeamIdentity:
    id: UUID
    org_id: UUID
    is_active: bool


@dataclass(frozen=True)
class WorkspaceProjectIdentity:
    id: UUID
    org_id: UUID
    team_id: UUID
    is_active: bool


@dataclass(frozen=True)
class WorkspaceVirtualKeyIdentity:
    id: UUID
    org_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class WorkspaceProjectOption:
    id: UUID
    name: str
    team_id: UUID


@dataclass(frozen=True)
class WorkspaceVirtualKeyOption:
    id: UUID
    name: str
    project_id: UUID
    project_name: str


@dataclass(frozen=True)
class WorkspaceVirtualKeyTarget:
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    virtual_key_name: str | None


@dataclass(frozen=True)
class WorkspaceFilterValidation:
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    project: WorkspaceProjectIdentity | None = None


@dataclass(frozen=True)
class WorkspaceAllowedScopeIds:
    team_ids: set[UUID]
    project_ids: set[UUID]
    virtual_key_ids: set[UUID]


@dataclass(frozen=True)
class WorkspaceLabel:
    id: UUID
    name: str


@dataclass(frozen=True)
class WorkspaceLabelMaps:
    teams: dict[UUID, str]
    projects: dict[UUID, str]
    virtual_keys: dict[UUID, str]
