from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import InvalidAccessTokenError
from app.modules.auth.internal.models import TeamMembership
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal.models import Allocation, Project

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


def require_team_admin_or_permission(permission: str) -> Callable:
    async def check(
        team_id: str,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        db: DatabaseSession,
    ) -> AuthenticatedUser:
        if auth_facade.has_permission(user, permission) or await _is_team_admin(
            team_id=team_id,
            user=user,
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
        if project and await _is_team_admin(team_id=str(project.team_id), user=user, db=db):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    return check


async def require_allocation_team_admin_or_permission(
    *,
    allocation_id: str,
    permission: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> None:
    if auth_facade.has_permission(user, permission):
        return
    try:
        parsed_allocation_id = UUID(str(allocation_id))
    except ValueError:
        parsed_allocation_id = None
    if parsed_allocation_id is None:
        return
    allocation = await db.scalar(
        select(Allocation).where(
            Allocation.id == parsed_allocation_id,
            Allocation.org_id == user.org_id,
        )
    )
    if allocation is None:
        return
    team_id = allocation.team_id
    if team_id is None and allocation.project_id is not None:
        project = await _get_project(project_id=str(allocation.project_id), user=user, db=db)
        team_id = project.team_id if project else None
    if team_id and await _is_team_admin(team_id=str(team_id), user=user, db=db):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


async def require_team_view_or_permission(
    *,
    team_id: str,
    permission: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> None:
    if auth_facade.has_permission(user, permission) or await _has_team_membership(
        team_id=team_id,
        user=user,
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
    if project and await _has_team_membership(team_id=str(project.team_id), user=user, db=db):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


async def require_allocation_target_team_admin_or_permission(
    *,
    team_id: str | None,
    project_id: str | None,
    permission: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> None:
    if auth_facade.has_permission(user, permission):
        return
    target_team_id = team_id
    if target_team_id is None and project_id is not None:
        project = await _get_project(project_id=project_id, user=user, db=db)
        target_team_id = str(project.team_id) if project else None
    if target_team_id and await _is_team_admin(team_id=target_team_id, user=user, db=db):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="insufficient permissions",
    )


def accessible_team_ids(user: AuthenticatedUser) -> set[UUID]:
    return {membership.team_id for membership in user.team_memberships}


def get_scope(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> Scope:
    return Scope(org_id=user.org_id)


async def _has_team_membership(*, team_id: str, user: AuthenticatedUser, db: AsyncSession) -> bool:
    try:
        parsed_team_id = UUID(str(team_id))
    except ValueError:
        return False
    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.org_id == user.org_id,
            TeamMembership.team_id == parsed_team_id,
            TeamMembership.user_id == user.id,
        )
    )
    return membership is not None


async def _is_team_admin(*, team_id: str, user: AuthenticatedUser, db: AsyncSession) -> bool:
    try:
        parsed_team_id = UUID(str(team_id))
    except ValueError:
        return False
    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.org_id == user.org_id,
            TeamMembership.team_id == parsed_team_id,
            TeamMembership.user_id == user.id,
            TeamMembership.role == "team_admin",
        )
    )
    return membership is not None


async def _get_project(
    *, project_id: str, user: AuthenticatedUser, db: AsyncSession
) -> Project | None:
    try:
        parsed_project_id = UUID(str(project_id))
    except ValueError:
        return None
    return await db.scalar(
        select(Project).where(
            Project.id == parsed_project_id,
            Project.org_id == user.org_id,
        )
    )
