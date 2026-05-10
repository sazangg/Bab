from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.audit import facade
from app.modules.audit.schemas import AuditEvent
from app.modules.auth.schemas import AuthenticatedUser

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def list_audit_logs(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AuditEvent]:
    return await facade.list_events(org_id=scope.org_id, db=db, limit=limit)
