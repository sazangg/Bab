from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.request_logs import facade
from app.modules.request_logs.schemas import RequestLogResponse

router = APIRouter(prefix="/request-logs", tags=["request-logs"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def list_request_logs(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RequestLogResponse]:
    return await facade.list_request_logs(scope=scope, limit=limit, db=db)
