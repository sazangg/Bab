from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
    require_project_team_admin_or_permission,
    require_project_view_or_permission,
)
from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    MemberNotFoundError,
    PermissionDeniedError,
)
from app.modules.auth.schemas import (
    AuthenticatedUser,
    MemberOptionResponse,
    ProjectMemberResponse,
    UpdateProjectMemberRequest,
    UpsertProjectMemberRequest,
)
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.keys import facade
from app.modules.keys.errors import (
    AccessDeniedError,
    PolicyNotConfiguredError,
    ProjectAccessUnavailableError,
    SecretDeliveryDisabledError,
    VirtualKeyAlreadyRevokedError,
    VirtualKeyNotFoundError,
    VirtualKeyOverlapActiveError,
)
from app.modules.keys.schemas import (
    AccessibleModel,
    CreatedVirtualKeyResponse,
    CreateVirtualKeyRequest,
    EffectiveAccessSummary,
    RevokeVirtualKeyRequest,
    RotateVirtualKeyRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
    VirtualKeyRevokeImpactResponse,
)
from app.modules.teams.errors import TeamInactiveError
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import OrganizationUsageSummary, VirtualKeyUsageSummary
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import (
    OrganizationInactiveError,
    ProjectInactiveError,
    ProjectNotFoundError,
    ProjectSlugAlreadyExistsError,
)
from app.modules.workspace.schemas import (
    ProjectArchiveImpactResponse,
    ProjectResponse,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
VirtualKeyAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_project_team_admin_or_permission(Permissions.KEYS_MANAGE)),
]
ProjectAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_project_team_admin_or_permission(Permissions.PROJECTS_MANAGE)),
]


@router.get("")
async def list_projects(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[ProjectResponse]:
    projects = await workspace_facade.list_projects(scope=scope, db=db)
    if authorization_facade.has_permission(user, Permissions.PROJECTS_VIEW):
        return projects
    allowed_scopes = authorization_facade.authorized_workspace_ids(user, relationship="member")
    return [
        project
        for project in projects
        if project.team_id in allowed_scopes.team_ids or project.id in allowed_scopes.project_ids
    ]


@router.patch("/{project_id}")
async def update_project(
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectResponse:
    try:
        return await workspace_facade.update_project(
            project_id=project_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ProjectSlugAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="project slug already exists") from exc


@router.get("/{project_id}/usage")
async def get_project_usage(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> OrganizationUsageSummary:
    try:
        await workspace_facade.get_project(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    await require_project_view_or_permission(
        project_id=str(project_id),
        permission=Permissions.PROJECTS_VIEW,
        user=user,
        db=db,
    )
    return await usage_facade.get_organization_usage_summary(
        org_id=scope.org_id,
        project_id=project_id,
        window="30d",
        db=db,
    )


@router.get("/{project_id}/archive-impact")
async def get_project_archive_impact(
    project_id: UUID,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectArchiveImpactResponse:
    try:
        return await workspace_facade.get_project_archive_impact(
            project_id=project_id,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}")
async def get_project(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> ProjectResponse:
    try:
        project = await workspace_facade.get_project(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    if not authorization_facade.has_permission(user, Permissions.PROJECTS_VIEW):
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission="",
            user=user,
            db=db,
        )
    return project


@router.get("/{project_id}/keys")
async def list_virtual_keys(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[VirtualKeyResponse]:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission=Permissions.PROJECTS_VIEW,
            user=user,
            db=db,
        )
        return await facade.list_virtual_keys(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/{project_id}/keys", status_code=status.HTTP_201_CREATED)
async def create_virtual_key(
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CreatedVirtualKeyResponse:
    try:
        return await facade.create_virtual_key(
            project_id=project_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectAccessUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.summary.blocking_code,
                "message": exc.summary.blocking_reason,
                "effective_access": exc.summary.model_dump(mode="json"),
            },
        ) from exc
    except SecretDeliveryDisabledError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "secret_delivery_disabled",
                "message": (
                    "Virtual key creation is disabled because plaintext secret delivery "
                    "is turned off."
                ),
            },
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ProjectInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_archived",
                "message": "Virtual key cannot be created because the project is archived.",
            },
        ) from exc
    except TeamInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "team_archived",
                "message": "Virtual key cannot be created because the owning team is archived.",
            },
        ) from exc
    except OrganizationInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "organization_inactive",
                "message": "Virtual key cannot be created because the organization is inactive.",
            },
        ) from exc


@router.get("/{project_id}/members")
async def list_project_members(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[ProjectMemberResponse]:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission=Permissions.PROJECTS_VIEW,
            user=user,
            db=db,
        )
        return await auth_facade.list_project_members(project_id=project_id, scope=scope, db=db)
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}/member-options")
async def list_project_member_options(
    project_id: UUID,
    _: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[MemberOptionResponse]:
    return await auth_facade.list_member_options(scope=scope, db=db)


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: UUID,
    payload: UpsertProjectMemberRequest,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectMemberResponse:
    try:
        return await auth_facade.upsert_project_member(
            project_id=project_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="project or user not found") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.patch("/{project_id}/members/{user_id}")
async def update_project_member(
    project_id: UUID,
    user_id: UUID,
    payload: UpdateProjectMemberRequest,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectMemberResponse:
    try:
        return await auth_facade.update_project_member(
            project_id=project_id,
            user_id=user_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="project or user not found") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await auth_facade.remove_project_member(
            project_id=project_id,
            user_id=user_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="project or user not found") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.get("/{project_id}/accessible-models")
async def list_project_accessible_models(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[AccessibleModel]:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission=Permissions.PROJECTS_VIEW,
            user=user,
            db=db,
        )
        return await facade.list_project_accessible_models(
            project_id=project_id,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except PolicyNotConfiguredError as exc:
        raise HTTPException(
            status_code=409,
            detail="project has no effective access policy",
        ) from exc


@router.get("/{project_id}/effective-access")
async def get_project_effective_access(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> EffectiveAccessSummary:
    await require_project_view_or_permission(
        project_id=str(project_id), permission=Permissions.PROJECTS_VIEW, user=user, db=db
    )
    try:
        return await facade.get_project_effective_access(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}/keys/{key_id}")
async def get_virtual_key(
    project_id: UUID,
    key_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> VirtualKeyResponse:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission=Permissions.PROJECTS_VIEW,
            user=user,
            db=db,
        )
        return await facade.get_virtual_key(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc


@router.get("/{project_id}/keys/{key_id}/usage")
async def get_virtual_key_usage(
    project_id: UUID,
    key_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> VirtualKeyUsageSummary:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission=Permissions.PROJECTS_VIEW,
            user=user,
            db=db,
        )
        await facade.get_virtual_key(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc
    return await usage_facade.get_virtual_key_usage_summary(
        virtual_key_id=key_id,
        org_id=scope.org_id,
        db=db,
    )


@router.patch("/{project_id}/keys/{key_id}")
async def update_virtual_key(
    project_id: UUID,
    key_id: UUID,
    payload: UpdateVirtualKeyRequest,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> VirtualKeyResponse:
    try:
        return await facade.update_virtual_key(
            project_id=project_id,
            key_id=key_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc
    except PolicyNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail="policy not found") from exc
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=403,
            detail="policy is not available to this key",
        ) from exc


@router.post(
    "/{project_id}/keys/{key_id}/rotate",
    status_code=status.HTTP_201_CREATED,
)
async def rotate_virtual_key(
    project_id: UUID,
    key_id: UUID,
    payload: RotateVirtualKeyRequest,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CreatedVirtualKeyResponse:
    try:
        return await facade.rotate_virtual_key(
            project_id=project_id,
            key_id=key_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc
    except VirtualKeyAlreadyRevokedError as exc:
        raise HTTPException(status_code=409, detail="virtual key is already revoked") from exc
    except SecretDeliveryDisabledError as exc:
        raise HTTPException(status_code=409, detail="secret delivery is disabled") from exc


@router.get("/{project_id}/keys/{key_id}/revoke-impact")
async def get_virtual_key_revoke_impact(
    project_id: UUID,
    key_id: UUID,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> VirtualKeyRevokeImpactResponse:
    try:
        return await facade.get_virtual_key_revoke_impact(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc


@router.delete("/{project_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_virtual_key(
    project_id: UUID,
    key_id: UUID,
    payload: RevokeVirtualKeyRequest,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.revoke_virtual_key(
            project_id=project_id,
            key_id=key_id,
            reason=payload.reason.strip(),
            force=payload.force,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc
    except VirtualKeyAlreadyRevokedError as exc:
        raise HTTPException(status_code=409, detail="virtual key is already revoked") from exc
    except VirtualKeyOverlapActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "rotation_overlap_active",
                "message": "rotation overlap is still active; confirm early revocation",
                "deprecated_at": exc.deprecated_at.isoformat(),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/keys/{key_id}/effective-access")
async def get_virtual_key_effective_access(
    project_id: UUID,
    key_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> EffectiveAccessSummary:
    await require_project_view_or_permission(
        project_id=str(project_id), permission=Permissions.PROJECTS_VIEW, user=user, db=db
    )
    try:
        return await facade.get_virtual_key_effective_access(
            project_id=project_id, key_id=key_id, scope=scope, db=db
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_project(
    project_id: UUID,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await workspace_facade.deactivate_project(
            project_id=project_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
