from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import generate_virtual_key, hash_token
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    ModelAliasAlreadyExistsError,
    ModelAliasNotFoundError,
    ProjectAllocationNotFoundError,
    ProjectNotFoundError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import (
    ModelAlias,
    Project,
    ProjectAllocation,
    VirtualKey,
)
from app.modules.keys.schemas import (
    CreatedVirtualKeyResponse,
    CreateModelAliasRequest,
    CreateProjectAllocationRequest,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ModelAliasResponse,
    ProjectAllocationResponse,
    ProjectResponse,
    ResolveAccessRequest,
    ResolvedAccess,
    UpdateModelAliasRequest,
    UpdateProjectAllocationRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
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


async def create_project_allocation(
    *,
    project_id: UUID,
    payload: CreateProjectAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectAllocationResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        await providers_facade.get_provider(provider_id=payload.provider_id, scope=scope, db=db)
        await _validate_model_offerings_belong_to_provider(
            provider_id=payload.provider_id,
            model_offering_ids=payload.model_offering_ids,
            scope=scope,
            db=db,
        )
        allocation = await repository.upsert_project_allocation(
            org_id=scope.org_id,
            project_id=project.id,
            provider_id=payload.provider_id,
            model_offering_ids=_uuid_list_to_json(payload.model_offering_ids),
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_allocation.saved",
                target_type="project_allocation",
                target_id=allocation.id,
                event_metadata={
                    "project_id": str(project.id),
                    "provider_id": str(payload.provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_allocation_saved",
        project_id=str(project_id),
        provider_id=str(payload.provider_id),
        org_id=str(scope.org_id),
    )
    return _allocation_to_response(allocation)


async def list_project_allocations(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectAllocationResponse]:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    allocations = await repository.list_project_allocations(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [_allocation_to_response(allocation) for allocation in allocations]


async def update_project_allocation(
    *,
    project_id: UUID,
    provider_id: UUID,
    payload: UpdateProjectAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectAllocationResponse:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        allocation = await _get_project_allocation_or_raise(
            project_id=project_id,
            provider_id=provider_id,
            scope=scope,
            db=db,
        )
        if "model_offering_ids" in payload.model_fields_set:
            await _validate_model_offerings_belong_to_provider(
                provider_id=provider_id,
                model_offering_ids=payload.model_offering_ids,
                scope=scope,
                db=db,
            )
            allocation.model_offering_ids = _uuid_list_to_json(payload.model_offering_ids)
        if payload.is_active is not None:
            allocation.is_active = payload.is_active
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_allocation.updated",
                target_type="project_allocation",
                target_id=allocation.id,
                event_metadata={
                    "project_id": str(project_id),
                    "provider_id": str(provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_allocation_updated",
        project_id=str(project_id),
        provider_id=str(provider_id),
        org_id=str(scope.org_id),
    )
    return _allocation_to_response(allocation)


async def revoke_project_allocation(
    *,
    project_id: UUID,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        allocation = await _get_project_allocation_or_raise(
            project_id=project_id,
            provider_id=provider_id,
            scope=scope,
            db=db,
        )
        allocation_id = allocation.id
        await repository.delete_project_allocation(allocation=allocation, db=db)
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_allocation.revoked",
                target_type="project_allocation",
                target_id=allocation_id,
                event_metadata={
                    "project_id": str(project_id),
                    "provider_id": str(provider_id),
                },
            ),
            db,
        )

    logger.info(
        "project_allocation_revoked",
        project_id=str(project_id),
        provider_id=str(provider_id),
        org_id=str(scope.org_id),
    )


async def _get_project_allocation_or_raise(
    *,
    project_id: UUID,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProjectAllocation:
    allocation = await repository.get_project_allocation(
        org_id=scope.org_id,
        project_id=project_id,
        provider_id=provider_id,
        db=db,
    )
    if allocation is None:
        raise ProjectAllocationNotFoundError
    return allocation


async def _validate_model_offerings_belong_to_provider(
    *,
    provider_id: UUID,
    model_offering_ids: list[UUID] | None,
    scope: Scope,
    db: AsyncSession,
) -> None:
    if model_offering_ids is None:
        return
    for model_offering_id in model_offering_ids:
        model_offering = await providers_facade.get_model_offering(
            model_offering_id=model_offering_id,
            scope=scope,
            db=db,
        )
        if model_offering.provider_id != provider_id:
            raise AccessDeniedError


def _allocation_to_response(allocation: ProjectAllocation) -> ProjectAllocationResponse:
    return ProjectAllocationResponse.model_validate(allocation)


def _uuid_list_to_json(values: list[UUID] | None) -> list[str] | None:
    if values is None:
        return None
    return [str(value) for value in values]


async def create_model_alias(
    *,
    payload: CreateModelAliasRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelAliasResponse:
    async with transaction(db):
        await _ensure_alias_name_available(alias=payload.alias, scope=scope, db=db)
        await providers_facade.get_provider(provider_id=payload.provider_id, scope=scope, db=db)
        model_alias = await repository.create_model_alias(
            org_id=scope.org_id,
            alias=payload.alias,
            provider_id=payload.provider_id,
            provider_model=payload.provider_model,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_alias.created",
                target_type="model_alias",
                target_id=model_alias.id,
                event_metadata={
                    "alias": model_alias.alias,
                    "provider_id": str(model_alias.provider_id),
                    "provider_model": model_alias.provider_model,
                },
            ),
            db,
        )

    logger.info(
        "model_alias_created",
        model_alias_id=str(model_alias.id),
        org_id=str(scope.org_id),
    )
    return _model_alias_to_response(model_alias)


async def list_model_aliases(*, scope: Scope, db: AsyncSession) -> list[ModelAliasResponse]:
    model_aliases = await repository.list_model_aliases(org_id=scope.org_id, db=db)
    return [_model_alias_to_response(model_alias) for model_alias in model_aliases]


async def update_model_alias(
    *,
    alias_id: UUID,
    payload: UpdateModelAliasRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelAliasResponse:
    async with transaction(db):
        model_alias = await _get_model_alias_or_raise(alias_id=alias_id, scope=scope, db=db)
        if payload.alias is not None and payload.alias != model_alias.alias:
            await _ensure_alias_name_available(alias=payload.alias, scope=scope, db=db)
            model_alias.alias = payload.alias
        if payload.provider_id is not None:
            await providers_facade.get_provider(provider_id=payload.provider_id, scope=scope, db=db)
            model_alias.provider_id = payload.provider_id
        if payload.provider_model is not None:
            model_alias.provider_model = payload.provider_model
        if payload.is_active is not None:
            model_alias.is_active = payload.is_active

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_alias.updated",
                target_type="model_alias",
                target_id=model_alias.id,
            ),
            db,
        )

    logger.info(
        "model_alias_updated",
        model_alias_id=str(model_alias.id),
        org_id=str(scope.org_id),
    )
    return _model_alias_to_response(model_alias)


async def deactivate_model_alias(
    *,
    alias_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        model_alias = await _get_model_alias_or_raise(alias_id=alias_id, scope=scope, db=db)
        model_alias.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_alias.deactivated",
                target_type="model_alias",
                target_id=model_alias.id,
            ),
            db,
        )

    logger.info(
        "model_alias_deactivated",
        model_alias_id=str(alias_id),
        org_id=str(scope.org_id),
    )


async def _ensure_alias_name_available(*, alias: str, scope: Scope, db: AsyncSession) -> None:
    existing = await repository.get_model_alias_by_name(alias=alias, org_id=scope.org_id, db=db)
    if existing is not None:
        raise ModelAliasAlreadyExistsError


async def _get_model_alias_or_raise(
    *, alias_id: UUID, scope: Scope, db: AsyncSession
) -> ModelAlias:
    model_alias = await repository.get_model_alias(alias_id=alias_id, org_id=scope.org_id, db=db)
    if model_alias is None:
        raise ModelAliasNotFoundError
    return model_alias


def _model_alias_to_response(model_alias: ModelAlias) -> ModelAliasResponse:
    return ModelAliasResponse.model_validate(model_alias)


async def create_virtual_key(
    *,
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        await _validate_virtual_key_restrictions(payload.restrictions, scope=scope, db=db)
        raw_key = generate_virtual_key()
        virtual_key = await repository.create_virtual_key(
            org_id=scope.org_id,
            project_id=project.id,
            name=payload.name,
            key_hash=hash_token(raw_key),
            key_prefix=_key_prefix(raw_key),
            restrictions=_restrictions_to_json(payload.restrictions),
            expires_at=payload.expires_at,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="virtual_key.created",
                target_type="virtual_key",
                target_id=virtual_key.id,
                event_metadata={"project_id": str(project.id), "name": virtual_key.name},
            ),
            db,
        )

    logger.info(
        "virtual_key_created",
        virtual_key_id=str(virtual_key.id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
    )
    return CreatedVirtualKeyResponse(
        **_virtual_key_to_response(virtual_key).model_dump(),
        key=raw_key,
    )


async def list_virtual_keys(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[VirtualKeyResponse]:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_keys = await repository.list_virtual_keys(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [_virtual_key_to_response(virtual_key) for virtual_key in virtual_keys]


async def get_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_key = await _get_virtual_key_or_raise(
        project_id=project_id,
        key_id=key_id,
        scope=scope,
        db=db,
    )
    return _virtual_key_to_response(virtual_key)


async def update_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: UpdateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        restrictions_changed = "restrictions" in payload.model_fields_set
        if payload.name is not None:
            virtual_key.name = payload.name
        if "expires_at" in payload.model_fields_set:
            virtual_key.expires_at = payload.expires_at
        if restrictions_changed:
            await _validate_virtual_key_restrictions(payload.restrictions, scope=scope, db=db)
            virtual_key.restrictions = _restrictions_to_json(payload.restrictions)

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="virtual_key.updated",
                target_type="virtual_key",
                target_id=virtual_key.id,
                event_metadata={"project_id": str(project_id)},
            ),
            db,
        )
        if restrictions_changed:
            await audit_facade.record_event(
                RecordAuditEvent(
                    org_id=scope.org_id,
                    actor_user_id=actor.id,
                    event="virtual_key.restrictions_updated",
                    target_type="virtual_key",
                    target_id=virtual_key.id,
                    event_metadata={"project_id": str(project_id)},
                ),
                db,
            )

    logger.info(
        "virtual_key_updated",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
    )
    return _virtual_key_to_response(virtual_key)


async def revoke_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        virtual_key.revoked_at = datetime.now(UTC)
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="virtual_key.revoked",
                target_type="virtual_key",
                target_id=virtual_key.id,
                event_metadata={"project_id": str(project_id)},
            ),
            db,
        )

    logger.info(
        "virtual_key_revoked",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
    )


async def _get_virtual_key_or_raise(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKey:
    virtual_key = await repository.get_virtual_key(
        org_id=scope.org_id,
        project_id=project_id,
        key_id=key_id,
        db=db,
    )
    if virtual_key is None:
        raise VirtualKeyNotFoundError
    return virtual_key


def _virtual_key_to_response(virtual_key: VirtualKey) -> VirtualKeyResponse:
    return VirtualKeyResponse.model_validate(virtual_key)


def _key_prefix(raw_key: str) -> str:
    return raw_key[:16]


def _restrictions_to_json(restrictions) -> list[dict[str, object]] | None:
    if restrictions is None:
        return None
    return [restriction.model_dump(mode="json") for restriction in restrictions]


async def _validate_virtual_key_restrictions(
    restrictions,
    *,
    scope: Scope,
    db: AsyncSession,
) -> None:
    if restrictions is None:
        return

    for restriction in restrictions:
        await providers_facade.get_provider(
            provider_id=restriction.provider_id,
            scope=scope,
            db=db,
        )


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    virtual_key = await repository.get_virtual_key_by_hash(
        key_hash=hash_token(payload.raw_key),
        db=db,
    )
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    project = await repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError

    resolved = await _resolve_allocation_access(
        payload=payload,
        virtual_key=virtual_key,
        db=db,
    )
    if resolved is None:
        raise AccessDeniedError

    return resolved


async def _resolve_allocation_access(
    *,
    payload: ResolveAccessRequest,
    virtual_key: VirtualKey,
    db: AsyncSession,
) -> ResolvedAccess | None:
    provider_id, provider_model, used_alias = await _resolve_requested_model(
        requested_model=payload.requested_model,
        requested_provider_id=payload.provider_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    scope = Scope(org_id=virtual_key.org_id)
    provider = await providers_facade.get_provider(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise AccessDeniedError
    if payload.provider is not None and provider.slug != payload.provider:
        raise AccessDeniedError

    allocation = await repository.get_project_allocation(
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        provider_id=provider_id,
        db=db,
    )
    if allocation is None:
        return None
    if not allocation.is_active:
        raise AccessDeniedError
    if not await _allocation_allows_model(
        allocation=allocation,
        provider_model=provider_model,
        scope=scope,
        db=db,
    ):
        raise AccessDeniedError
    if not _key_restrictions_allow(
        provider_id=provider_id,
        provider_model=provider_model,
        restrictions=virtual_key.restrictions,
    ):
        raise AccessDeniedError

    return ResolvedAccess(
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        virtual_key_id=virtual_key.id,
        provider_id=provider_id,
        requested_model=payload.requested_model,
        provider_model=provider_model,
        used_alias=used_alias,
    )


async def _allocation_allows_model(
    *,
    allocation: ProjectAllocation,
    provider_model: str,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    if allocation.model_offering_ids is None:
        return True
    allowed_ids = set(allocation.model_offering_ids)
    model_offerings = await providers_facade.list_model_offerings(
        provider_id=allocation.provider_id,
        search=None,
        modalities=None,
        is_active=True,
        limit=100,
        offset=0,
        scope=scope,
        db=db,
    )
    for model_offering in model_offerings.items:
        if str(model_offering.id) not in allowed_ids:
            continue
        if not model_offering.is_active:
            continue
        if model_offering.provider_model_name == provider_model:
            return True
        if model_offering.alias == provider_model:
            return True
    return False


async def _resolve_requested_model(
    *,
    requested_model: str,
    requested_provider_id: UUID | None,
    org_id: UUID,
    db: AsyncSession,
) -> tuple[UUID, str, bool]:
    alias = await repository.get_active_model_alias_by_name(
        alias=requested_model,
        org_id=org_id,
        db=db,
    )
    if alias is not None:
        return alias.provider_id, alias.provider_model, True

    if requested_provider_id is None:
        raise AccessDeniedError

    return requested_provider_id, requested_model, False


def _key_restrictions_allow(
    *,
    provider_id: UUID,
    provider_model: str,
    restrictions: list[dict[str, object]] | None,
) -> bool:
    if restrictions is None:
        return True

    for restriction in restrictions:
        if restriction.get("provider_id") != str(provider_id):
            continue
        allowed_models = restriction.get("allowed_models")
        if allowed_models is None:
            return True
        if isinstance(allowed_models, list) and provider_model in allowed_models:
            return True

    return False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
