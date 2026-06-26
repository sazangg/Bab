from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceScopeNotFoundError
from app.modules.workspace.schemas import WorkspaceProjectIdentity


class ResolvedWorkspaceFilterScope:
    def __init__(
        self,
        *,
        allowed_team_ids: set[UUID] | None,
        allowed_project_ids: set[UUID] | None,
    ) -> None:
        self.allowed_team_ids = allowed_team_ids
        self.allowed_project_ids = allowed_project_ids


async def resolve_workspace_filter_scope(
    *,
    user: AuthenticatedUser,
    org_id: UUID,
    db: AsyncSession,
    global_permission: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> ResolvedWorkspaceFilterScope:
    if authorization_facade.has_permission(user, global_permission):
        await _validate_filter_relationships(
            org_id=org_id,
            db=db,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )
        return ResolvedWorkspaceFilterScope(
            allowed_team_ids=None,
            allowed_project_ids=None,
        )

    allowed_scopes = authorization_facade.authorized_workspace_ids(user, relationship="member")
    allowed_team_ids = allowed_scopes.team_ids
    allowed_project_ids = allowed_scopes.project_ids
    if not allowed_team_ids and not allowed_project_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    project = await _validate_filter_relationships(
        org_id=org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    if team_id is not None and team_id not in allowed_team_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )
    if project is not None and (
        project.team_id not in allowed_team_ids and project.id not in allowed_project_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )
    return ResolvedWorkspaceFilterScope(
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
    )


async def _validate_filter_relationships(
    *,
    org_id: UUID,
    db: AsyncSession,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> WorkspaceProjectIdentity | None:
    try:
        validation = await workspace_facade.validate_filter_relationships(
            scope=Scope(org_id=org_id),
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
    except WorkspaceScopeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_filter_validation_error_detail(exc.reason),
        ) from exc
    return validation.project


def _filter_validation_error_detail(reason: str) -> str:
    if reason == "project_team_mismatch":
        return "project does not belong to team"
    if reason == "virtual_key_project_mismatch":
        return "virtual key does not belong to project"
    if reason == "virtual_key_team_mismatch":
        return "virtual key does not belong to team"
    return "insufficient permissions"
