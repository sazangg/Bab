from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.keys.schemas import EffectiveAccessSummary


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    team_id: UUID
    team_name: str | None = None
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectIdentity(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID
    is_active: bool


class ProjectMembershipTarget(BaseModel):
    id: UUID
    org_id: UUID
    team_id: UUID
    name: str
    is_active: bool


class ProjectOption(BaseModel):
    id: UUID
    name: str
    team_id: UUID


class TeamArchiveImpactResponse(BaseModel):
    active_project_count: int = 0
    active_virtual_key_count: int = 0
    team_admin_count: int = 0
    team_member_count: int = 0
    recent_usage_window_days: int = 30
    recent_request_count: int = 0
    recent_cost_cents: int = 0


class ProjectArchiveImpactResponse(BaseModel):
    active_virtual_key_count: int = 0
    recent_usage_window_days: int = 30
    recent_request_count: int = 0
    recent_cost_cents: int = 0
    effective_access: EffectiveAccessSummary


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
