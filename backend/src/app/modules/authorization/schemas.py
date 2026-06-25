from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthorizationTarget(BaseModel):
    kind: Literal["assignment_scope", "workspace_scope"]
    scope_type: Literal["org", "team", "project", "virtual_key"]
    relationship: Literal["admin", "member"] = "admin"
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None

    @classmethod
    def assignment_scope(
        cls,
        *,
        scope_type: Literal["org", "team", "project", "virtual_key"],
        team_id: UUID | None = None,
        project_id: UUID | None = None,
        virtual_key_id: UUID | None = None,
    ) -> "AuthorizationTarget":
        return cls(
            kind="assignment_scope",
            scope_type=scope_type,
            relationship="admin",
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )

    @classmethod
    def workspace_scope(
        cls,
        *,
        scope_type: Literal["org", "team", "project", "virtual_key"],
        relationship: Literal["admin", "member"] = "admin",
        team_id: UUID | None = None,
        project_id: UUID | None = None,
        virtual_key_id: UUID | None = None,
    ) -> "AuthorizationTarget":
        return cls(
            kind="workspace_scope",
            scope_type=scope_type,
            relationship=relationship,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )


class AuthorizedWorkspaceScopes(BaseModel):
    team_ids: set[UUID]
    project_ids: set[UUID]


class MemberRoleChangeTarget(BaseModel):
    target_user_id: UUID | None = None
    current_role: str | None = None
    new_role: str


class MemberStatusChangeTarget(BaseModel):
    target_user_id: UUID
    current_role: str
    new_status: str


class MemberInviteTarget(BaseModel):
    org_role: str
    team_id: UUID | None = None
    team_role: str | None = None
    project_id: UUID | None = None
    project_team_id: UUID | None = None
    project_role: str | None = None


class ScopedMembershipTarget(BaseModel):
    scope_type: Literal["team", "project"]
    team_id: UUID | None = None
    project_id: UUID | None = None
    project_team_id: UUID | None = None


class AuthorizationDecision(BaseModel):
    allowed: bool
    permission: str
    target_kind: str
    reason_code: str
    matched_permission: str | None = None
    matched_role: str | None = None
    scope_type: str | None = None
