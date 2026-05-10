from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.request_logs import facade
from app.modules.request_logs.schemas import RequestLogFilters, RequestLogResponse

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
    offset: Annotated[int, Query(ge=0)] = 0,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    status_code: Annotated[int | None, Query(ge=100, le=599)] = None,
    requested_model: Annotated[str | None, Query(max_length=255)] = None,
    provider_model: Annotated[str | None, Query(max_length=255)] = None,
) -> list[RequestLogResponse]:
    return await facade.list_request_logs(
        scope=scope,
        limit=limit,
        offset=offset,
        filters=RequestLogFilters(
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            provider_id=provider_id,
            status_code=status_code,
            requested_model=requested_model,
            provider_model=provider_model,
        ),
        db=db,
    )
