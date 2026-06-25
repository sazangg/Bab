from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.keys import facade
from app.modules.keys.schemas import VirtualKeyInventoryPage

router = APIRouter(prefix="/virtual-keys", tags=["virtual-keys"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def list_virtual_key_inventory(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    status: Literal[
        "active",
        "unused",
        "expiring_soon",
        "expired",
        "revoked",
        "project_archived",
        "team_archived",
        "no_effective_access",
    ]
    | None = None,
    search: str | None = Query(default=None, max_length=255),
    usage: Literal["used", "never"] | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> VirtualKeyInventoryPage:
    can_view_all = authorization_facade.has_permission(user, Permissions.PROJECTS_VIEW)
    visible_scopes = authorization_facade.authorized_workspace_ids(user, relationship="member")
    manageable_scopes = authorization_facade.authorized_workspace_ids(user, relationship="admin")
    return await facade.list_virtual_key_inventory(
        scope=scope,
        visible_team_ids=None if can_view_all else visible_scopes.team_ids,
        visible_project_ids=None if can_view_all else visible_scopes.project_ids,
        manageable_team_ids=manageable_scopes.team_ids,
        manageable_project_ids=manageable_scopes.project_ids,
        can_manage_all=authorization_facade.has_permission(user, Permissions.KEYS_MANAGE),
        team_id=team_id,
        project_id=project_id,
        status=status,
        search=search,
        usage=usage,
        limit=limit,
        offset=offset,
        db=db,
    )
