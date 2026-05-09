from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.errors import ProjectNotFoundError, ProjectProviderAccessNotFoundError
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import Project, ProjectProviderAccess
from app.modules.keys.schemas import (
    CreateProjectRequest,
    GrantProjectProviderAccessRequest,
    ProjectProviderAccessResponse,
    ProjectResponse,
    UpdateProjectProviderAccessRequest,
    UpdateProjectRequest,
)
from app.modules.providers import facade as providers_facade

logger = structlog.get_logger(__name__)


async def create_project(
    *,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    async with transaction(db):
        project = await repository.create_project(
            org_id=scope.org_id,
            created_by=actor.id,
            name=payload.name,
            description=payload.description,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project.created",
                target_type="project",
                target_id=project.id,
                event_metadata={"name": project.name},
            ),
            db,
        )

    logger.info("project_created", project_id=str(project.id), org_id=str(scope.org_id))
    return _to_response(project)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    projects = await repository.list_projects(org_id=scope.org_id, db=db)
    return [_to_response(project) for project in projects]


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
        if payload.name is not None:
            project.name = payload.name
        if "description" in payload.model_fields_set:
            project.description = payload.description
        if payload.is_active is not None:
            project.is_active = payload.is_active

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project.updated",
                target_type="project",
                target_id=project.id,
            ),
            db,
        )

    logger.info("project_updated", project_id=str(project.id), org_id=str(scope.org_id))
    return _to_response(project)


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
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project.deactivated",
                target_type="project",
                target_id=project.id,
            ),
            db,
        )

    logger.info("project_deactivated", project_id=str(project_id), org_id=str(scope.org_id))


async def _get_project_or_raise(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        raise ProjectNotFoundError
    return project


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse.model_validate(project)


async def grant_project_provider_access(
    *,
    project_id: UUID,
    payload: GrantProjectProviderAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectProviderAccessResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        await providers_facade.get_provider(provider_id=payload.provider_id, scope=scope, db=db)
        access = await repository.get_provider_access(
            org_id=scope.org_id,
            project_id=project.id,
            provider_id=payload.provider_id,
            db=db,
        )
        event = "project_provider_access.updated"
        if access is None:
            access = await repository.grant_provider_access(
                org_id=scope.org_id,
                project_id=project.id,
                provider_id=payload.provider_id,
                allowed_models=payload.allowed_models,
                db=db,
            )
            event = "project_provider_access.granted"
        else:
            access.allowed_models = payload.allowed_models
            await db.flush()

        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event=event,
                target_type="project_provider_access",
                target_id=access.id,
                event_metadata={
                    "project_id": str(project.id),
                    "provider_id": str(payload.provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_provider_access_saved",
        project_id=str(project_id),
        provider_id=str(payload.provider_id),
        org_id=str(scope.org_id),
    )
    return _access_to_response(access)


async def list_project_provider_access(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectProviderAccessResponse]:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    access_rules = await repository.list_provider_access(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [_access_to_response(access) for access in access_rules]


async def update_project_provider_access(
    *,
    project_id: UUID,
    provider_id: UUID,
    payload: UpdateProjectProviderAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectProviderAccessResponse:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        access = await _get_provider_access_or_raise(
            project_id=project_id,
            provider_id=provider_id,
            scope=scope,
            db=db,
        )
        access.allowed_models = payload.allowed_models
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_provider_access.updated",
                target_type="project_provider_access",
                target_id=access.id,
                event_metadata={
                    "project_id": str(project_id),
                    "provider_id": str(provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_provider_access_updated",
        project_id=str(project_id),
        provider_id=str(provider_id),
        org_id=str(scope.org_id),
    )
    return _access_to_response(access)


async def revoke_project_provider_access(
    *,
    project_id: UUID,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        access = await _get_provider_access_or_raise(
            project_id=project_id,
            provider_id=provider_id,
            scope=scope,
            db=db,
        )
        access_id = access.id
        await repository.delete_provider_access(access=access, db=db)
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_provider_access.revoked",
                target_type="project_provider_access",
                target_id=access_id,
                event_metadata={
                    "project_id": str(project_id),
                    "provider_id": str(provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_provider_access_revoked",
        project_id=str(project_id),
        provider_id=str(provider_id),
        org_id=str(scope.org_id),
    )


async def _get_provider_access_or_raise(
    *,
    project_id: UUID,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProjectProviderAccess:
    access = await repository.get_provider_access(
        org_id=scope.org_id,
        project_id=project_id,
        provider_id=provider_id,
        db=db,
    )
    if access is None:
        raise ProjectProviderAccessNotFoundError
    return access


def _access_to_response(access: ProjectProviderAccess) -> ProjectProviderAccessResponse:
    return ProjectProviderAccessResponse.model_validate(access)
