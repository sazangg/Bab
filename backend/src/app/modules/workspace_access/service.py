from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal import repository as keys_repository
from app.modules.teams.internal import repository as teams_repository
from app.modules.workspace_access.types import ValidatedScope


class ScopeAccessDeniedError(Exception):
    pass


class ScopeNotFoundError(Exception):
    def __init__(self, reason: str = "not_found") -> None:
        self.reason = reason
        super().__init__(reason)


class WorkspaceAccessService:
    async def require_assignment_admin(
        self,
        *,
        actor: AuthenticatedUser,
        scope: Scope,
        scope_type: str,
        db: AsyncSession,
        team_id: UUID | None = None,
        project_id: UUID | None = None,
        virtual_key_id: UUID | None = None,
        global_permissions: set[str] | None = None,
    ) -> None:
        if self._is_global_assignment_admin(actor, global_permissions=global_permissions):
            return
        if scope_type == "org":
            raise ScopeAccessDeniedError
        if await self.can_manage_assignment_scope(
            actor=actor,
            scope=scope,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        ):
            return
        raise ScopeAccessDeniedError

    async def can_manage_assignment_scope(
        self,
        *,
        actor: AuthenticatedUser,
        scope: Scope,
        scope_type: str,
        db: AsyncSession,
        team_id: UUID | None = None,
        project_id: UUID | None = None,
        virtual_key_id: UUID | None = None,
    ) -> bool:
        team_admin_ids, project_admin_ids = self.managed_scope_ids(actor)
        if scope_type == "team":
            if team_id is None:
                return False
            team = await teams_repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
            return team is not None and team_id in team_admin_ids
        if scope_type == "project":
            if project_id is None:
                return False
            project = await keys_repository.get_project(
                org_id=scope.org_id,
                project_id=project_id,
                db=db,
            )
            return project is not None and (
                project.team_id in team_admin_ids or project.id in project_admin_ids
            )
        if scope_type == "virtual_key":
            if virtual_key_id is None:
                return False
            virtual_key = await keys_repository.get_virtual_key_by_id(
                org_id=scope.org_id,
                key_id=virtual_key_id,
                db=db,
            )
            if virtual_key is None:
                return False
            project = await keys_repository.get_project(
                org_id=scope.org_id,
                project_id=virtual_key.project_id,
                db=db,
            )
            return project is not None and (
                project.team_id in team_admin_ids or project.id in project_admin_ids
            )
        return False

    async def validate_assignment_scope(
        self,
        *,
        organization_id: UUID,
        scope_type: str,
        db: AsyncSession,
        team_id: UUID | None = None,
        project_id: UUID | None = None,
        virtual_key_id: UUID | None = None,
    ) -> ValidatedScope:
        if scope_type == "org":
            if team_id is not None or project_id is not None or virtual_key_id is not None:
                raise ScopeNotFoundError("invalid")
            return ValidatedScope(scope_type="org")
        if scope_type == "team":
            if team_id is None or project_id is not None or virtual_key_id is not None:
                raise ScopeNotFoundError("invalid")
            team = await teams_repository.get_team(org_id=organization_id, team_id=team_id, db=db)
            if team is None:
                raise ScopeNotFoundError
            return ValidatedScope(scope_type="team", team_id=team_id)
        if scope_type == "project":
            if project_id is None or virtual_key_id is not None:
                raise ScopeNotFoundError("invalid")
            project = await keys_repository.get_project(
                org_id=organization_id,
                project_id=project_id,
                db=db,
            )
            if project is None:
                raise ScopeNotFoundError
            if team_id is not None and team_id != project.team_id:
                raise ScopeNotFoundError("invalid")
            return ValidatedScope(scope_type="project", project_id=project_id)
        if scope_type == "virtual_key":
            if virtual_key_id is None:
                raise ScopeNotFoundError("invalid")
            virtual_key = await keys_repository.get_virtual_key_by_id(
                org_id=organization_id,
                key_id=virtual_key_id,
                db=db,
            )
            if virtual_key is None:
                raise ScopeNotFoundError
            project = await keys_repository.get_project(
                org_id=organization_id,
                project_id=virtual_key.project_id,
                db=db,
            )
            if project is None:
                raise ScopeNotFoundError
            if project_id is not None and project_id != virtual_key.project_id:
                raise ScopeNotFoundError("invalid")
            if team_id is not None and team_id != project.team_id:
                raise ScopeNotFoundError("invalid")
            return ValidatedScope(scope_type="virtual_key", virtual_key_id=virtual_key_id)
        raise ScopeNotFoundError("invalid")

    def managed_scope_ids(self, actor: AuthenticatedUser) -> tuple[set[UUID], set[UUID]]:
        team_admin_ids = {
            membership.team_id
            for membership in actor.team_memberships
            if membership.role == "team_admin"
        }
        project_admin_ids = {
            membership.project_id
            for membership in actor.project_memberships
            if membership.role == "project_admin"
        }
        return team_admin_ids, project_admin_ids

    def _is_global_assignment_admin(
        self,
        actor: AuthenticatedUser,
        *,
        global_permissions: set[str] | None,
    ) -> bool:
        if "*" in actor.permissions or actor.role in {"org_owner", "org_admin"}:
            return True
        return bool(global_permissions and global_permissions.intersection(actor.permissions))
