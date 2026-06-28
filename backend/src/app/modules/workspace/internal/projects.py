import re
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.workspace.errors import (
    ProjectNotFoundError,
    ProjectSlugAlreadyExistsError,
    TeamInactiveError,
    TeamNotFoundError,
)
from app.modules.workspace.internal import repository
from app.modules.workspace.internal.models import Project, Team
from app.modules.workspace.schemas import (
    CreateProjectRequest,
    ProjectIdentity,
    ProjectMembershipTarget,
    ProjectOption,
    ProjectResponse,
    UpdateProjectRequest,
)

logger = structlog.get_logger(__name__)


async def create_project(
    *,
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    slug = _slugify(payload.slug or payload.name)
    async with transaction(db):
        await repository.ensure_organization_active(org_id=scope.org_id, db=db)
        await _ensure_team_active(team_id=team_id, scope=scope, db=db)
        await _ensure_project_slug_available(
            org_id=scope.org_id,
            team_id=team_id,
            slug=slug,
            db=db,
        )
        try:
            project = await repository.create_project(
                org_id=scope.org_id,
                team_id=team_id,
                created_by=actor.id,
                name=payload.name,
                slug=slug,
                description=payload.description,
                db=db,
            )
        except IntegrityError as exc:
            raise ProjectSlugAlreadyExistsError from exc
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.created",
            message=f"Created project {project.name}.",
            team_id=team_id,
            project_id=project.id,
            metadata={"project_id": str(project.id), "team_id": str(team_id)},
            db=db,
        )
    logger.info("project_created", project_id=str(project.id), org_id=str(scope.org_id))
    return await _to_project_response(project, db=db)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    projects = await repository.list_projects(org_id=scope.org_id, db=db)
    return [await _to_project_response(project, db=db) for project in projects]


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return await _to_project_response(project, db=db)


async def get_project_identity(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectIdentity | None:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        return None
    return ProjectIdentity(
        id=project.id,
        org_id=project.org_id,
        team_id=project.team_id,
        is_active=project.is_active,
    )


async def get_project_membership_target(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectMembershipTarget | None:
    row = await repository.get_project_membership_target(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    if row is None:
        return None
    project_id, org_id, team_id, name, is_active = row
    return ProjectMembershipTarget(
        id=project_id,
        org_id=org_id,
        team_id=team_id,
        name=name,
        is_active=is_active,
    )


async def get_project_team_ids(
    *, scope: Scope, project_ids: set[UUID] | None = None, db: AsyncSession
) -> dict[UUID, UUID]:
    return await repository.get_project_team_ids(
        org_id=scope.org_id,
        project_ids=project_ids,
        db=db,
    )


async def list_team_projects(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectResponse]:
    await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
    projects = await repository.list_team_projects(org_id=scope.org_id, team_id=team_id, db=db)
    return [await _to_project_response(project, db=db) for project in projects]


async def update_project(
    *,
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        changed_fields: dict[str, dict[str, object]] = {}
        if payload.slug is not None:
            slug = _slugify(payload.slug)
            if slug != project.slug:
                await _ensure_project_slug_available(
                    org_id=scope.org_id,
                    team_id=project.team_id,
                    slug=slug,
                    db=db,
                )
                changed_fields["slug"] = {"from": project.slug, "to": slug}
                project.slug = slug
        if payload.name is not None:
            if payload.name != project.name:
                changed_fields["name"] = {"from": project.name, "to": payload.name}
            project.name = payload.name
        if "description" in payload.model_fields_set:
            if payload.description != project.description:
                changed_fields["description"] = {
                    "from": project.description,
                    "to": payload.description,
                }
            project.description = payload.description
        if payload.is_active is not None:
            if payload.is_active != project.is_active:
                changed_fields["is_active"] = {"from": project.is_active, "to": payload.is_active}
            project.is_active = payload.is_active
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ProjectSlugAlreadyExistsError from exc
        action = (
            "project.reactivated"
            if changed_fields.get("is_active", {}).get("to") is True
            else "project.deactivated"
            if changed_fields.get("is_active", {}).get("to") is False
            else "project.updated"
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action=action,
            message=f"Updated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            metadata={
                "project_id": str(project.id),
                "team_id": str(project.team_id),
                "changed_fields": changed_fields,
            },
            db=db,
        )
    logger.info(
        "project_updated",
        project_id=str(project.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return await _to_project_response(project, db=db)


async def deactivate_project(
    *,
    project_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        project.is_active = False
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.deactivated",
            message=f"Deactivated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            metadata={"project_id": str(project.id), "team_id": str(project.team_id)},
            db=db,
        )
    logger.info(
        "project_deactivated",
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )




async def get_project_labels(
    *, project_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await repository.get_project_labels(
        org_id=scope.org_id,
        project_ids=project_ids,
        db=db,
    )




async def list_project_ids_for_team_ids(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> set[UUID]:
    return await repository.list_project_ids_for_team_ids(
        org_id=scope.org_id,
        team_ids=team_ids,
        db=db,
    )




async def list_project_options(
    *,
    scope: Scope,
    team_ids: set[UUID] | None,
    project_ids: set[UUID] | None,
    db: AsyncSession,
) -> list[ProjectOption]:
    rows = await repository.list_project_options(
        org_id=scope.org_id,
        team_ids=team_ids,
        project_ids=project_ids,
        db=db,
    )
    return [
        ProjectOption(id=project_id, name=name, team_id=team_id)
        for project_id, name, team_id in rows
    ]




async def _get_project_or_raise(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        raise ProjectNotFoundError
    return project


async def _get_team_or_raise(*, team_id: UUID, scope: Scope, db: AsyncSession) -> Team:
    team = await repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
    if team is None:
        raise TeamNotFoundError
    return team


async def _ensure_team_active(*, team_id: UUID, scope: Scope, db: AsyncSession) -> Team:
    team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
    if not team.is_active:
        raise TeamInactiveError
    return team


async def _ensure_project_slug_available(
    *, org_id: UUID, team_id: UUID, slug: str, db: AsyncSession
) -> None:
    existing = await repository.get_project_by_slug(
        org_id=org_id,
        team_id=team_id,
        slug=slug,
        db=db,
    )
    if existing is not None:
        raise ProjectSlugAlreadyExistsError


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


async def _to_project_response(project: Project, *, db: AsyncSession) -> ProjectResponse:
    team_labels = await repository.get_team_labels(
        org_id=project.org_id,
        team_ids={project.team_id},
        db=db,
    )
    return ProjectResponse.model_validate(project).model_copy(
        update={"team_name": team_labels.get(project.team_id)}
    )


