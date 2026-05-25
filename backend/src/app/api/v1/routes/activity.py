from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_scope, require_permission
from app.core.database import Scope, get_db
from app.modules.activity import facade
from app.modules.activity.schemas import ActivityEventResponse
from app.modules.auth.schemas import AuthenticatedUser

router = APIRouter(prefix="/activity", tags=["activity"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
ActivityViewer = Annotated[AuthenticatedUser, Depends(require_permission("activity.view"))]


@router.get("")
async def list_activity_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: ActivityViewer,
    category: str | None = None,
    severity: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ActivityEventResponse]:
    return await facade.list_events(
        org_id=scope.org_id,
        category=category,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        db=db,
    )
