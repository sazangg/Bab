from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import InvalidAccessTokenError
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.errors import AuthorizationDeniedError
from app.modules.authorization.schemas import AuthorizationTarget
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.schemas import WorkspaceProjectIdentity

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
BearerToken = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(token: BearerToken, db: DatabaseSession) -> AuthenticatedUser:
    try:
        return await auth_facade.verify_access_token(token, db)
    except InvalidAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_role(*roles: str) -> Callable:
    async def check(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not authorization_facade.has_any_role(user, set(roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return user

    return check


def require_permission(permission: str) -> Callable:
    async def check(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not authorization_facade.has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return user

    return check


def require_permission_or_scoped_admin(permission: str) -> Callable:
    async def check(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        admin_scopes = authorization_facade.authorized_workspace_ids(
            user,
            relationship="admin",
        )
        if authorization_facade.has_permission(user, permission) or (
            admin_scopes.team_ids or admin_scopes.project_ids
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    return check


def require_team_admin_or_permission(permission: str) -> Callable:
    async def check(
        team_id: str,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        db: DatabaseSession,
    ) -> AuthenticatedUser:
        if authorization_facade.has_permission(user, permission):
            return user
        parsed_team_id = _parse_uuid(team_id)
        if parsed_team_id is not None and await _can_access_workspace(
            user=user,
            permission=permission,
            target=AuthorizationTarget.workspace_scope(
                scope_type="team",
                relationship="admin",
                team_id=parsed_team_id,
            ),
            db=db,
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    return check


def require_project_team_admin_or_permission(permission: str) -> Callable:
    async def check(
        project_id: str,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        db: DatabaseSession,
    ) -> AuthenticatedUser:
        if authorization_facade.has_permission(user, permission):
            return user
        project = await _get_project(project_id=project_id, user=user, db=db)
        if project and await _can_access_workspace(
            user=user,
            permission=permission,
            target=AuthorizationTarget.workspace_scope(
                scope_type="project",
                relationship="admin",
                project_id=project.id,
            ),
            db=db,
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    return check


async def require_team_view_or_permission(
    *,
    team_id: str,
    permission: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> None:
    if authorization_facade.has_permission(user, permission):
        return
    parsed_team_id = _parse_uuid(team_id)
    if parsed_team_id is not None and await _can_access_workspace(
        user=user,
        permission=permission,
        target=AuthorizationTarget.workspace_scope(
            scope_type="team",
            relationship="member",
            team_id=parsed_team_id,
        ),
        db=db,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


async def require_project_view_or_permission(
    *,
    project_id: str,
    permission: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> None:
    if authorization_facade.has_permission(user, permission):
        return
    project = await _get_project(project_id=project_id, user=user, db=db)
    if project and await _can_access_workspace(
        user=user,
        permission=permission,
        target=AuthorizationTarget.workspace_scope(
            scope_type="project",
            relationship="member",
            project_id=project.id,
        ),
        db=db,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


def get_scope(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> Scope:
    return Scope(org_id=user.org_id)


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _can_access_workspace(
    *,
    user: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    db: AsyncSession,
) -> bool:
    try:
        await authorization_facade.require(
            actor=user,
            permission=permission,
            target=target,
            scope=Scope(org_id=user.org_id),
            db=db,
        )
        return True
    except AuthorizationDeniedError:
        return False


async def _get_project(
    *, project_id: str, user: AuthenticatedUser, db: AsyncSession
) -> WorkspaceProjectIdentity | None:
    try:
        parsed_project_id = UUID(str(project_id))
    except ValueError:
        return None
    return await workspace_facade.get_project_identity(
        project_id=parsed_project_id,
        scope=Scope(org_id=user.org_id),
        db=db,
    )
