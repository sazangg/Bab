from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
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
from app.modules.usage.schemas import AllocationUsageSummary, VirtualKeyUsageSummary

router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AllocationAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]
VirtualKeyAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_projects(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProjectResponse]:
    return await facade.list_projects(scope=scope, db=db)


@router.patch("/{project_id}")
async def update_project(
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: CurrentUser,
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
    _: CurrentUser,
) -> list[AllocationResponse]:
    try:
        return await facade.list_project_allocations(project_id=project_id, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/{project_id}/allocations/usage")
async def list_project_allocation_usage(
    project_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[AllocationUsageSummary]:
    try:
        allocations = await facade.list_project_allocations(
            project_id=project_id, scope=scope, db=db
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return [
        await usage_facade.get_allocation_usage_summary(
            allocation_id=allocation.id,
            org_id=scope.org_id,
            db=db,
        )
        for allocation in allocations
    ]


@router.get("/allocations")
async def list_allocations(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[AllocationResponse]:
    return await facade.list_allocations(scope=scope, db=db)


@router.post("/allocations", status_code=status.HTTP_201_CREATED)
async def create_allocation(
    payload: CreateAllocationRequest,
    actor: AllocationAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AllocationResponse:
    try:
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
    actor: AllocationAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AllocationResponse:
    try:
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
    _: CurrentUser,
) -> list[VirtualKeyResponse]:
    try:
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
    _: CurrentUser,
) -> VirtualKeyResponse:
    try:
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
    _: CurrentUser,
) -> VirtualKeyUsageSummary:
    try:
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
    actor: CurrentUser,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_project(project_id=project_id, actor=actor, scope=scope, db=db)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
