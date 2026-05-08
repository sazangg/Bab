from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade
from app.modules.keys.errors import ProjectNotFoundError
from app.modules.keys.schemas import CreateProjectRequest, ProjectResponse, UpdateProjectRequest

router = APIRouter(prefix="/projects", tags=["projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def list_projects(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProjectResponse]:
    return await facade.list_projects(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: CreateProjectRequest,
    actor: CurrentUser,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectResponse:
    return await facade.create_project(payload=payload, actor=actor, scope=scope, db=db)


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
