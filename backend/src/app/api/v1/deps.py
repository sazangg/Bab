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
        if user.role not in roles and "*" not in user.permissions:
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
        if not auth_facade.has_permission(user, permission):
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
        if (
            auth_facade.has_permission(user, permission)
            or any(item.role == "team_admin" for item in user.team_memberships)
            or any(item.role == "project_admin" for item in user.project_memberships)
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
        if auth_facade.has_permission(user, permission) or await _is_team_admin(
            team_id=team_id,
            actor=user,
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
        if auth_facade.has_permission(user, permission):
            return user
        project = await _get_project(project_id=project_id, user=user, db=db)
        if project and (
            await _is_team_admin(team_id=str(project.team_id), actor=user, db=db)
            or await _is_project_admin(project_id=str(project.id), actor=user, db=db)
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
    if auth_facade.has_permission(user, permission) or await _has_team_membership(
        team_id=team_id,
        actor=user,
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
    if auth_facade.has_permission(user, permission):
        return
    project = await _get_project(project_id=project_id, user=user, db=db)
    if project and (
        await _has_team_membership(team_id=str(project.team_id), actor=user, db=db)
        or await _has_project_membership(project_id=str(project.id), actor=user, db=db)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


def accessible_team_ids(user: AuthenticatedUser) -> set[UUID]:
    return {membership.team_id for membership in user.team_memberships}


def accessible_project_ids(user: AuthenticatedUser) -> set[UUID]:
    return {membership.project_id for membership in user.project_memberships}


def get_scope(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> Scope:
    return Scope(org_id=user.org_id)


async def _has_team_membership(
    *, team_id: str, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    try:
        parsed_team_id = UUID(str(team_id))
    except ValueError:
        return False
    return await workspace_facade.has_team_membership(
        team_id=parsed_team_id,
        actor=actor,
        db=db,
    )


async def _is_team_admin(*, team_id: str, actor: AuthenticatedUser, db: AsyncSession) -> bool:
    try:
        parsed_team_id = UUID(str(team_id))
    except ValueError:
        return False
    return await workspace_facade.is_team_admin(
        team_id=parsed_team_id,
        actor=actor,
        db=db,
    )


async def _has_project_membership(
    *, project_id: str, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    try:
        parsed_project_id = UUID(str(project_id))
    except ValueError:
        return False
    return await workspace_facade.has_project_membership(
        project_id=parsed_project_id,
        actor=actor,
        db=db,
    )


async def _is_project_admin(
    *, project_id: str, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    try:
        parsed_project_id = UUID(str(project_id))
    except ValueError:
        return False
    return await workspace_facade.is_project_admin(
        project_id=parsed_project_id,
        actor=actor,
        db=db,
    )


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
