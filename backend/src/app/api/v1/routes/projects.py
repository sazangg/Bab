from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    accessible_team_ids,
    get_current_user,
    get_scope,
    require_allocation_target_team_admin_or_permission,
    require_allocation_team_admin_or_permission,
    require_permission,
    require_project_team_admin_or_permission,
    require_project_view_or_permission,
)
from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade
from app.modules.keys.errors import (
    AccessDeniedError,
    AllocationNotFoundError,
    ProjectNotFoundError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.schemas import (
    AllocationResponse,
    CreateAllocationRequest,
    CreatedVirtualKeyResponse,
    CreateVirtualKeyRequest,
    ProjectResponse,
    UpdateAllocationRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
)
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import (
    AllocationUsageSummary,
    OrganizationUsageSummary,
    VirtualKeyUsageSummary,
)

router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
ProjectViewer = Annotated[AuthenticatedUser, Depends(require_permission("projects.view"))]
VirtualKeyAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_project_team_admin_or_permission("keys.manage")),
]
ProjectAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_project_team_admin_or_permission("projects.manage")),
]


@router.get("")
async def list_projects(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[ProjectResponse]:
    projects = await facade.list_projects(scope=scope, db=db)
    if auth_facade.has_permission(user, "projects.view"):
        return projects
    allowed_ids = accessible_team_ids(user)
    return [project for project in projects if project.team_id in allowed_ids]


@router.patch("/{project_id}")
async def update_project(
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: ProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectResponse:
    try:
        return await facade.update_project(
            project_id=project_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}/allocations")
async def list_project_allocations(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[AllocationResponse]:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission="projects.view",
            user=user,
            db=db,
        )
        return await facade.list_project_allocations(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}/usage")
async def get_project_usage(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> OrganizationUsageSummary:
    try:
        await facade.get_project(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    await require_project_view_or_permission(
        project_id=str(project_id),
        permission="projects.view",
        user=user,
        db=db,
    )
    return await usage_facade.get_organization_usage_summary(
        org_id=scope.org_id,
        project_id=project_id,
        window="30d",
        db=db,
    )


@router.get("/{project_id}/allocations/usage")
async def list_project_allocation_usage(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[AllocationUsageSummary]:
    try:
        await require_project_view_or_permission(
            project_id=str(project_id),
            permission="projects.view",
            user=user,
            db=db,
        )
        allocations = await facade.list_project_allocations(
            project_id=project_id, scope=scope, db=db
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return [
        await usage_facade.get_allocation_usage_summary(
            allocation_id=allocation.id,
            org_id=scope.org_id,
            window=allocation.window,
            db=db,
        )
        for allocation in allocations
    ]


@router.get("/allocations")
async def list_allocations(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[AllocationResponse]:
    allocations = await facade.list_allocations(scope=scope, db=db)
    if auth_facade.has_permission(user, "projects.view"):
        return allocations
    allowed_team_ids = accessible_team_ids(user)
    if not allowed_team_ids:
        return []
    projects = await facade.list_projects(scope=scope, db=db)
    allowed_project_ids = {
        project.id for project in projects if project.team_id in allowed_team_ids
    }
    return [
        allocation
        for allocation in allocations
        if allocation.team_id in allowed_team_ids or allocation.project_id in allowed_project_ids
    ]


@router.get("/{project_id}")
async def get_project(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> ProjectResponse:
    try:
        project = await facade.get_project(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    await require_project_view_or_permission(
        project_id=str(project_id),
        permission="projects.view",
        user=user,
        db=db,
    )
    return project


@router.post("/allocations", status_code=status.HTTP_201_CREATED)
async def create_allocation(
    payload: CreateAllocationRequest,
    actor: CurrentUser,
    scope: RequestScope,
    db: DatabaseSession,
) -> AllocationResponse:
    try:
        await require_allocation_target_team_admin_or_permission(
            team_id=str(payload.team_id) if payload.team_id else None,
            project_id=str(payload.project_id) if payload.project_id else None,
            permission="allocations.manage",
            user=actor,
            db=db,
        )
        return await facade.create_allocation(
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pool or model offering not found") from exc
    except AllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="parent allocation not found") from exc


@router.patch("/allocations/{allocation_id}")
async def update_allocation(
    allocation_id: UUID,
    payload: UpdateAllocationRequest,
    actor: CurrentUser,
    scope: RequestScope,
    db: DatabaseSession,
) -> AllocationResponse:
    try:
        await require_allocation_team_admin_or_permission(
            allocation_id=str(allocation_id),
            permission="allocations.manage",
            user=actor,
            db=db,
        )
        return await facade.update_allocation(
            allocation_id=allocation_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except AllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="allocation not found") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pool or model offering not found") from exc


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
            permission="projects.view",
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
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except AllocationNotFoundError as exc:
        raise HTTPException(status_code=409, detail="project has no effective allocation") from exc


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
            permission="projects.view",
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
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


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
            permission="projects.view",
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
    except AllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="allocation not found") from exc
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=403,
            detail="allocation is not available to this key",
        ) from exc


@router.delete("/{project_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_virtual_key(
    project_id: UUID,
    key_id: UUID,
    actor: VirtualKeyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.revoke_virtual_key(
            project_id=project_id,
            key_id=key_id,
            actor=actor,
            scope=scope,
            db=db,
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
        await facade.deactivate_project(project_id=project_id, actor=actor, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
