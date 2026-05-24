from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import generate_virtual_key, hash_token
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.errors import (
    AccessDeniedError,
    AllocationNotFoundError,
    InvalidVirtualKeyError,
    ProjectNotFoundError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import Allocation, Project, VirtualKey
from app.modules.keys.schemas import (
    AccessibleModel,
    AllocationOffering,
    AllocationResponse,
    CreateAllocationRequest,
    CreatedVirtualKeyResponse,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ProjectResponse,
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedAllocationLimit,
    UpdateAllocationRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.settings import facade as settings_facade
from app.modules.teams import facade as teams_facade

logger = structlog.get_logger(__name__)


async def create_project(
    *,
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    async with transaction(db):
        await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
        project = await repository.create_project(
            org_id=scope.org_id,
            team_id=team_id,
            created_by=actor.id,
            name=payload.name,
            description=payload.description,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.created",
            message=f"Created project {project.name}.",
            team_id=team_id,
            project_id=project.id,
            db=db,
        )
    logger.info("project_created", project_id=str(project.id), org_id=str(scope.org_id))
    return _to_project_response(project)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    projects = await repository.list_projects(org_id=scope.org_id, db=db)
    return [_to_project_response(project) for project in projects]


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return _to_project_response(project)


async def list_team_projects(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectResponse]:
    await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
    projects = await repository.list_team_projects(org_id=scope.org_id, team_id=team_id, db=db)
    return [_to_project_response(project) for project in projects]


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
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.updated",
            message=f"Updated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            db=db,
        )
    logger.info(
        "project_updated",
        project_id=str(project.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _to_project_response(project)


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
            db=db,
        )
    logger.info(
        "project_deactivated",
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


async def create_allocation(
    *,
    payload: CreateAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> AllocationResponse:
    async with transaction(db):
        project = await _validate_allocation_target(payload=payload, scope=scope, db=db)
        parent_allocation_id = payload.parent_allocation_id
        parent_allocation = None
        if project is not None and parent_allocation_id is None:
            parent_allocation = await repository.get_default_team_allocation(
                org_id=scope.org_id,
                team_id=project.team_id,
                db=db,
            )
            parent_allocation_id = parent_allocation.id if parent_allocation else None
        if payload.parent_allocation_id is not None:
            parent_allocation = await _get_allocation_or_raise(
                allocation_id=payload.parent_allocation_id,
                scope=scope,
                db=db,
            )
        await _validate_offerings(payload.offerings, scope=scope, db=db)
        if payload.is_default:
            await repository.clear_default_allocations(
                org_id=scope.org_id,
                team_id=payload.team_id,
                project_id=payload.project_id,
                db=db,
            )
        allocation = await repository.create_allocation(
            org_id=scope.org_id,
            parent_allocation_id=parent_allocation_id,
            target_type="project" if payload.project_id is not None else "team",
            team_id=payload.team_id,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            offerings=_offerings_to_json(payload.offerings),
            is_default=payload.is_default,
            budget_cents=payload.budget_cents,
            max_requests=payload.max_requests,
            max_input_tokens=payload.max_input_tokens,
            max_output_tokens=payload.max_output_tokens,
            max_tokens_per_request=payload.max_tokens_per_request,
            window=payload.window,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="allocation",
            action="allocation.created",
            message=f"Created allocation {allocation.name}.",
            team_id=allocation.team_id,
            project_id=allocation.project_id,
            allocation_id=allocation.id,
            db=db,
        )
    logger.info(
        "allocation_created",
        allocation_id=str(allocation.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _to_allocation_response(allocation)


async def list_allocations(*, scope: Scope, db: AsyncSession) -> list[AllocationResponse]:
    allocations = await repository.list_allocations(org_id=scope.org_id, db=db)
    return [_to_allocation_response(allocation) for allocation in allocations]


async def list_team_allocations(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[AllocationResponse]:
    await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
    allocations = await repository.list_team_allocations(
        org_id=scope.org_id,
        team_id=team_id,
        db=db,
    )
    return [_to_allocation_response(allocation) for allocation in allocations]


async def list_project_allocations(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[AllocationResponse]:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    allocations = await repository.list_project_allocations(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [_to_allocation_response(allocation) for allocation in allocations]


async def update_allocation(
    *,
    allocation_id: UUID,
    payload: UpdateAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> AllocationResponse:
    async with transaction(db):
        allocation = await _get_allocation_or_raise(
            allocation_id=allocation_id,
            scope=scope,
            db=db,
        )
        if payload.name is not None:
            allocation.name = payload.name
        if "description" in payload.model_fields_set:
            allocation.description = payload.description
        if payload.offerings is not None:
            await _validate_offerings(payload.offerings, scope=scope, db=db)
            allocation.offerings = _offerings_to_json(payload.offerings)
        for field in (
            "budget_cents",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_tokens_per_request",
            "window",
        ):
            if field in payload.model_fields_set:
                setattr(allocation, field, getattr(payload, field))
        if payload.is_default is not None:
            if payload.is_default:
                await repository.clear_default_allocations(
                    org_id=scope.org_id,
                    team_id=allocation.team_id,
                    project_id=allocation.project_id,
                    db=db,
                )
            allocation.is_default = payload.is_default
        if payload.is_active is not None:
            allocation.is_active = payload.is_active
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="allocation",
            action="allocation.updated",
            message=f"Updated allocation {allocation.name}.",
            team_id=allocation.team_id,
            project_id=allocation.project_id,
            allocation_id=allocation.id,
            db=db,
        )
    logger.info(
        "allocation_updated",
        allocation_id=str(allocation_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _to_allocation_response(allocation)


async def create_virtual_key(
    *,
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        if payload.allocation_id is not None:
            allocation = await _get_allocation_or_raise(
                allocation_id=payload.allocation_id,
                scope=scope,
                db=db,
            )
            if allocation.project_id != project.id:
                raise AccessDeniedError
        else:
            allocation = await _resolve_effective_allocation(project=project, scope=scope, db=db)
            if allocation is None:
                raise AllocationNotFoundError
        raw_key = generate_virtual_key(prefix=org_settings.virtual_key_prefix)
        expires_at = payload.expires_at
        if expires_at is None and org_settings.default_virtual_key_expiration_days is not None:
            expires_at = datetime.now(UTC) + timedelta(
                days=org_settings.default_virtual_key_expiration_days
            )
        virtual_key = await repository.create_virtual_key(
            org_id=scope.org_id,
            project_id=project.id,
            allocation_id=allocation.id,
            custom_allocation_id=payload.allocation_id,
            name=payload.name,
            key_hash=hash_token(raw_key),
            key_prefix=_key_prefix(raw_key),
            allowed_models=payload.allowed_models,
            expires_at=expires_at,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.created",
            message=f"Created virtual key {virtual_key.name}.",
            team_id=project.team_id,
            project_id=project.id,
            allocation_id=allocation.id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_created",
        virtual_key_id=str(virtual_key.id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return CreatedVirtualKeyResponse(
        **_to_virtual_key_response(virtual_key).model_dump(),
        key=raw_key if org_settings.allow_secret_copy else None,
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
    return [_to_virtual_key_response(virtual_key) for virtual_key in virtual_keys]


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
    return _to_virtual_key_response(virtual_key)


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
        if payload.name is not None:
            virtual_key.name = payload.name
        if "expires_at" in payload.model_fields_set:
            virtual_key.expires_at = payload.expires_at
        if "allowed_models" in payload.model_fields_set:
            virtual_key.allowed_models = payload.allowed_models
        if "custom_allocation_id" in payload.model_fields_set:
            if payload.custom_allocation_id is None:
                effective_allocation = await _resolve_effective_allocation(
                    project=await _get_project_or_raise(project_id=project_id, scope=scope, db=db),
                    scope=scope,
                    db=db,
                )
                if effective_allocation is None:
                    raise AllocationNotFoundError
                virtual_key.allocation_id = effective_allocation.id
                virtual_key.custom_allocation_id = None
            else:
                allocation = await _get_allocation_or_raise(
                    allocation_id=payload.custom_allocation_id,
                    scope=scope,
                    db=db,
                )
                if allocation.project_id != project_id:
                    raise AccessDeniedError
                virtual_key.allocation_id = allocation.id
                virtual_key.custom_allocation_id = allocation.id
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.updated",
            message=f"Updated virtual key {virtual_key.name}.",
            project_id=project_id,
            allocation_id=virtual_key.allocation_id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_updated",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _to_virtual_key_response(virtual_key)


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
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.revoked",
            message=f"Revoked virtual key {virtual_key.name}.",
            project_id=project_id,
            allocation_id=virtual_key.allocation_id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_revoked",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
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

    allocation = await repository.get_allocation(
        allocation_id=virtual_key.custom_allocation_id or virtual_key.allocation_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if allocation is None or not allocation.is_active:
        raise AccessDeniedError
    if allocation.project_id not in {None, project.id}:
        raise AccessDeniedError
    allocation_chain = [
        allocation,
        *await repository.get_parent_allocations(
            allocation=allocation,
            org_id=virtual_key.org_id,
            db=db,
        ),
    ]
    if any(not chain_allocation.is_active for chain_allocation in allocation_chain):
        raise AccessDeniedError

    matched = await _match_offering(
        allocation=allocation,
        requested_model=payload.requested_model,
        scope=Scope(org_id=virtual_key.org_id),
        db=db,
    )
    if matched is None:
        raise AccessDeniedError
    provider_id, pool_id, provider_model, input_price, output_price = matched
    for ancestor in allocation_chain[1:]:
        if not await _allocation_allows_route(
            allocation=ancestor,
            provider_id=provider_id,
            pool_id=pool_id,
            provider_model=provider_model,
            scope=Scope(org_id=virtual_key.org_id),
            db=db,
        ):
            raise AccessDeniedError

    if virtual_key.allowed_models is not None and provider_model not in virtual_key.allowed_models:
        raise AccessDeniedError

    return ResolvedAccess(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=virtual_key.project_id,
        allocation_id=allocation.id,
        allocation_chain_ids=[chain_allocation.id for chain_allocation in allocation_chain],
        allocation_limits=[
            _to_resolved_allocation_limit(chain_allocation) for chain_allocation in allocation_chain
        ],
        virtual_key_id=virtual_key.id,
        provider_id=provider_id,
        pool_id=pool_id,
        provider_key_id=None,
        requested_model=payload.requested_model,
        provider_model=provider_model,
        input_price_per_million_tokens=input_price,
        output_price_per_million_tokens=output_price,
    )


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    virtual_key = await repository.get_virtual_key_by_hash(key_hash=hash_token(raw_key), db=db)
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
    allocation = await repository.get_allocation(
        allocation_id=virtual_key.custom_allocation_id or virtual_key.allocation_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if allocation is None or not allocation.is_active:
        raise AccessDeniedError

    models: list[AccessibleModel] = []
    seen: set[str] = set()
    for offering in allocation.offerings:
        pool_id = UUID(str(offering["pool_id"]))
        model_offering_id = UUID(str(offering["model_offering_id"]))
        try:
            pool = await providers_facade.get_credential_pool(
                pool_id=pool_id,
                scope=Scope(org_id=virtual_key.org_id),
                db=db,
            )
            model = await providers_facade.get_model_offering(
                model_offering_id=model_offering_id,
                scope=Scope(org_id=virtual_key.org_id),
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if not pool.is_active or not model.is_active or pool.provider_id != model.provider_id:
            continue
        if (
            virtual_key.allowed_models is not None
            and model.provider_model_name not in virtual_key.allowed_models
        ):
            continue
        if model.provider_model_name in seen:
            continue
        seen.add(model.provider_model_name)
        models.append(
            AccessibleModel(
                id=model.provider_model_name,
                owned_by=model.provider_id.hex,
                provider_id=model.provider_id,
                allocation_id=allocation.id,
                pool_id=pool.id,
                alias=model.alias,
            )
        )
    return models


async def _match_offering(
    *,
    allocation: Allocation,
    requested_model: str,
    scope: Scope,
    db: AsyncSession,
) -> tuple[UUID, UUID, str, int | None, int | None] | None:
    for offering in allocation.offerings:
        pool_id = UUID(str(offering["pool_id"]))
        model_offering_id = UUID(str(offering["model_offering_id"]))
        try:
            pool = await providers_facade.get_credential_pool(pool_id=pool_id, scope=scope, db=db)
            model = await providers_facade.get_model_offering(
                model_offering_id=model_offering_id,
                scope=scope,
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if not pool.is_active or not model.is_active:
            continue
        if pool.provider_id != model.provider_id:
            continue
        if requested_model in {model.provider_model_name, model.alias}:
            return (
                model.provider_id,
                pool.id,
                model.provider_model_name,
                model.input_price_per_million_tokens,
                model.output_price_per_million_tokens,
            )
    return None


async def _allocation_allows_route(
    *,
    allocation: Allocation,
    provider_id: UUID,
    pool_id: UUID,
    provider_model: str,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    for offering in allocation.offerings:
        offering_pool_id = UUID(str(offering["pool_id"]))
        model_offering_id = UUID(str(offering["model_offering_id"]))
        if offering_pool_id != pool_id:
            continue
        try:
            model = await providers_facade.get_model_offering(
                model_offering_id=model_offering_id,
                scope=scope,
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if (
            model.is_active
            and model.provider_id == provider_id
            and model.provider_model_name == provider_model
        ):
            return True
    return False


async def _validate_allocation_target(
    *,
    payload: CreateAllocationRequest,
    scope: Scope,
    db: AsyncSession,
) -> Project | None:
    if payload.team_id is not None:
        await teams_facade.get_team(team_id=payload.team_id, scope=scope, db=db)
        return None
    if payload.project_id is not None:
        return await _get_project_or_raise(project_id=payload.project_id, scope=scope, db=db)
    return None


async def _validate_offerings(
    offerings: list[AllocationOffering],
    *,
    scope: Scope,
    db: AsyncSession,
) -> None:
    for offering in offerings:
        pool = await providers_facade.get_credential_pool(
            pool_id=offering.pool_id,
            scope=scope,
            db=db,
        )
        model = await providers_facade.get_model_offering(
            model_offering_id=offering.model_offering_id,
            scope=scope,
            db=db,
        )
        if pool.provider_id != model.provider_id:
            raise AccessDeniedError


async def _resolve_effective_allocation(
    *,
    project: Project,
    scope: Scope,
    db: AsyncSession,
) -> Allocation | None:
    project_allocation = await repository.get_default_project_allocation(
        org_id=scope.org_id,
        project_id=project.id,
        db=db,
    )
    if project_allocation is not None:
        return project_allocation
    return await repository.get_default_team_allocation(
        org_id=scope.org_id,
        team_id=project.team_id,
        db=db,
    )


async def _get_project_or_raise(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        raise ProjectNotFoundError
    return project


async def _get_allocation_or_raise(
    *,
    allocation_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> Allocation:
    allocation = await repository.get_allocation(
        allocation_id=allocation_id,
        org_id=scope.org_id,
        db=db,
    )
    if allocation is None:
        raise AllocationNotFoundError
    return allocation


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


def _to_project_response(project: Project) -> ProjectResponse:
    return ProjectResponse.model_validate(project)


def _to_allocation_response(allocation: Allocation) -> AllocationResponse:
    return AllocationResponse.model_validate(allocation)


def _to_resolved_allocation_limit(allocation: Allocation) -> ResolvedAllocationLimit:
    return ResolvedAllocationLimit(
        allocation_id=allocation.id,
        budget_cents=allocation.budget_cents,
        max_requests=allocation.max_requests,
        max_input_tokens=allocation.max_input_tokens,
        max_output_tokens=allocation.max_output_tokens,
        max_tokens_per_request=allocation.max_tokens_per_request,
        window=allocation.window,
    )


def _to_virtual_key_response(virtual_key: VirtualKey) -> VirtualKeyResponse:
    return VirtualKeyResponse(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        allocation_id=virtual_key.allocation_id,
        custom_allocation_id=virtual_key.custom_allocation_id,
        allocation_mode="custom" if virtual_key.custom_allocation_id else "inherited",
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        allowed_models=virtual_key.allowed_models,
        expires_at=virtual_key.expires_at,
        revoked_at=virtual_key.revoked_at,
        created_at=virtual_key.created_at,
        updated_at=virtual_key.updated_at,
    )


def _offerings_to_json(offerings: list[AllocationOffering]) -> list[dict[str, str]]:
    return [offering.model_dump(mode="json") for offering in offerings]


def _key_prefix(raw_key: str) -> str:
    return raw_key[:16]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
