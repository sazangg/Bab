from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal import service
from app.modules.keys.schemas import CreateProjectRequest, ProjectResponse, UpdateProjectRequest


async def create_project(
    *,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await service.create_project(payload=payload, actor=actor, scope=scope, db=db)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    return await service.list_projects(scope=scope, db=db)


async def update_project(
    *,
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await service.update_project(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_project(
    *,
    project_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_project(project_id=project_id, actor=actor, scope=scope, db=db)
