from dataclasses import dataclass
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
    ProjectNotFoundError,
    ProjectProviderAccessNotFoundError,
    SubscriptionNotFoundError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import (
    ModelAlias,
    Project,
    ProjectProviderAccess,
    ProjectSubscriptionAccess,
    Subscription,
    SubscriptionModelAccess,
    SubscriptionProviderKey,
    VirtualKey,
)
from app.modules.keys.schemas import (
    AttachSubscriptionProviderKeyRequest,
    CreatedVirtualKeyResponse,
    CreateModelAliasRequest,
    CreateProjectRequest,
    CreateSubscriptionRequest,
    CreateVirtualKeyRequest,
    GrantProjectProviderAccessRequest,
    GrantProjectSubscriptionAccessRequest,
    ModelAliasResponse,
    ProjectProviderAccessResponse,
    ProjectResponse,
    ProjectSubscriptionAccessResponse,
    ResolveAccessRequest,
    ResolvedAccess,
    SetSubscriptionModelAccessRequest,
    SubscriptionModelAccessResponse,
    SubscriptionProviderKeyResponse,
    SubscriptionResponse,
    UpdateModelAliasRequest,
    UpdateProjectProviderAccessRequest,
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


async def create_subscription(
    *,
    payload: CreateSubscriptionRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> SubscriptionResponse:
    async with transaction(db):
        subscription = await repository.create_subscription(
            org_id=scope.org_id,
            name=payload.name,
            description=payload.description,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="subscription.created",
                target_type="subscription",
                target_id=subscription.id,
                event_metadata={"name": subscription.name},
            ),
            db,
        )

    logger.info("subscription_created", subscription_id=str(subscription.id))
    return _subscription_to_response(subscription)


async def list_subscriptions(*, scope: Scope, db: AsyncSession) -> list[SubscriptionResponse]:
    subscriptions = await repository.list_subscriptions(org_id=scope.org_id, db=db)
    return [_subscription_to_response(subscription) for subscription in subscriptions]


async def attach_provider_key_to_subscription(
    *,
    subscription_id: UUID,
    payload: AttachSubscriptionProviderKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> SubscriptionProviderKeyResponse:
    async with transaction(db):
        subscription = await _get_subscription_or_raise(
            subscription_id=subscription_id,
            scope=scope,
            db=db,
        )
        await providers_facade.get_provider_key(
            provider_key_id=payload.provider_key_id,
            scope=scope,
            db=db,
        )
        attachment = await repository.attach_provider_key_to_subscription(
            org_id=scope.org_id,
            subscription_id=subscription.id,
            provider_key_id=payload.provider_key_id,
            priority=payload.priority,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="subscription_provider_key.attached",
                target_type="subscription_provider_key",
                target_id=attachment.id,
                event_metadata={
                    "subscription_id": str(subscription.id),
                    "provider_key_id": str(payload.provider_key_id),
                },
            ),
            db,
        )

    return _subscription_provider_key_to_response(attachment)


async def list_subscription_provider_keys(
    *,
    subscription_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionProviderKeyResponse]:
    await _get_subscription_or_raise(subscription_id=subscription_id, scope=scope, db=db)
    attachments = await repository.list_subscription_provider_keys(
        org_id=scope.org_id,
        subscription_id=subscription_id,
        db=db,
    )
    return [_subscription_provider_key_to_response(attachment) for attachment in attachments]


async def set_subscription_model_access(
    *,
    subscription_id: UUID,
    payload: SetSubscriptionModelAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionModelAccessResponse]:
    async with transaction(db):
        subscription = await _get_subscription_or_raise(
            subscription_id=subscription_id,
            scope=scope,
            db=db,
        )
        await repository.delete_subscription_model_access(
            org_id=scope.org_id,
            subscription_id=subscription.id,
            db=db,
        )
        access_rules: list[SubscriptionModelAccess] = []
        if payload.provider_model_ids is not None:
            provider_models = []
            for provider_model_id in set(payload.provider_model_ids):
                provider_models.append(
                    await providers_facade.get_provider_model(
                        provider_model_id=provider_model_id,
                        scope=scope,
                        db=db,
                    )
                )
            for provider_model in sorted(
                provider_models,
                key=lambda model: model.provider_model_name,
            ):
                access_rules.append(
                    await repository.add_subscription_model_access(
                        org_id=scope.org_id,
                        subscription_id=subscription.id,
                        provider_model_id=provider_model.id,
                        db=db,
                    )
                )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="subscription_model_access.updated",
                target_type="subscription",
                target_id=subscription.id,
                event_metadata={"model_count": len(access_rules)},
            ),
            db,
        )

    return [_subscription_model_access_to_response(access) for access in access_rules]


async def list_subscription_model_access(
    *,
    subscription_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionModelAccessResponse]:
    await _get_subscription_or_raise(subscription_id=subscription_id, scope=scope, db=db)
    access_rules = await repository.list_subscription_model_access(
        org_id=scope.org_id,
        subscription_id=subscription_id,
        db=db,
    )
    return [_subscription_model_access_to_response(access) for access in access_rules]


async def grant_project_subscription_access(
    *,
    project_id: UUID,
    payload: GrantProjectSubscriptionAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectSubscriptionAccessResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        subscription = await _get_subscription_or_raise(
            subscription_id=payload.subscription_id,
            scope=scope,
            db=db,
        )
        access = await repository.grant_project_subscription_access(
            org_id=scope.org_id,
            project_id=project.id,
            subscription_id=subscription.id,
            priority=payload.priority,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="project_subscription_access.granted",
                target_type="project_subscription_access",
                target_id=access.id,
                event_metadata={
                    "project_id": str(project.id),
                    "subscription_id": str(subscription.id),
                },
            ),
            db,
        )

    return _project_subscription_access_to_response(access)


async def list_project_subscription_access(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectSubscriptionAccessResponse]:
    await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    access_rules = await repository.list_project_subscription_access(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [_project_subscription_access_to_response(access) for access in access_rules]


async def _get_subscription_or_raise(
    *,
    subscription_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> Subscription:
    subscription = await repository.get_subscription(
        org_id=scope.org_id,
        subscription_id=subscription_id,
        db=db,
    )
    if subscription is None:
        raise SubscriptionNotFoundError
    return subscription


def _subscription_to_response(subscription: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(subscription)


def _subscription_provider_key_to_response(
    attachment: SubscriptionProviderKey,
) -> SubscriptionProviderKeyResponse:
    return SubscriptionProviderKeyResponse.model_validate(attachment)


def _subscription_model_access_to_response(
    access: SubscriptionModelAccess,
) -> SubscriptionModelAccessResponse:
    return SubscriptionModelAccessResponse.model_validate(access)


def _project_subscription_access_to_response(
    access: ProjectSubscriptionAccess,
) -> ProjectSubscriptionAccessResponse:
    return ProjectSubscriptionAccessResponse.model_validate(access)


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

    subscription_match = await _resolve_subscription_access(
        payload=payload,
        virtual_key=virtual_key,
        db=db,
    )
    if subscription_match is not None:
        return subscription_match

    provider_id, provider_model, used_alias = await _resolve_requested_model(
        requested_model=payload.requested_model,
        requested_provider_id=payload.provider_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    provider_access = await repository.get_provider_access(
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        provider_id=provider_id,
        db=db,
    )
    if provider_access is None:
        raise AccessDeniedError

    if not _model_allowed(provider_model, provider_access.allowed_models):
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


@dataclass(frozen=True)
class _SubscriptionModelMatch:
    provider_id: UUID
    provider_model: str
    used_alias: bool
    priority: int


async def _resolve_subscription_access(
    *,
    payload: ResolveAccessRequest,
    virtual_key: VirtualKey,
    db: AsyncSession,
) -> ResolvedAccess | None:
    scope = Scope(org_id=virtual_key.org_id)
    matches: list[_SubscriptionModelMatch] = []
    project_access_rules = await repository.list_project_subscription_access(
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        db=db,
    )

    for project_access in project_access_rules:
        if not project_access.is_active:
            continue
        subscription = await repository.get_subscription(
            org_id=virtual_key.org_id,
            subscription_id=project_access.subscription_id,
            db=db,
        )
        if subscription is None or not subscription.is_active:
            continue

        model_access = await repository.list_subscription_model_access(
            org_id=virtual_key.org_id,
            subscription_id=subscription.id,
            db=db,
        )
        allowed_provider_model_ids = {
            item.provider_model_id for item in model_access if item.is_active
        }
        provider_key_attachments = await repository.list_subscription_provider_keys(
            org_id=virtual_key.org_id,
            subscription_id=subscription.id,
            db=db,
        )
        for attachment in provider_key_attachments:
            if not attachment.is_active:
                continue
            provider_key = await providers_facade.get_provider_key(
                provider_key_id=attachment.provider_key_id,
                scope=scope,
                db=db,
            )
            if not provider_key.is_active:
                continue
            provider = await providers_facade.get_provider(
                provider_id=provider_key.provider_id,
                scope=scope,
                db=db,
            )
            if not provider.is_active:
                continue
            if payload.provider is not None and provider.slug != payload.provider:
                continue
            if payload.provider_id is not None and provider.id != payload.provider_id:
                continue

            provider_models = await providers_facade.list_provider_models(
                provider_id=provider.id,
                scope=scope,
                db=db,
            )
            for provider_model in provider_models:
                if not provider_model.is_active:
                    continue
                if (
                    allowed_provider_model_ids
                    and provider_model.id not in allowed_provider_model_ids
                ):
                    continue
                used_alias = (
                    provider_model.alias == payload.requested_model
                    and provider_model.provider_model_name != payload.requested_model
                )
                if provider_model.provider_model_name != payload.requested_model and not used_alias:
                    continue
                if not _key_restrictions_allow(
                    provider_id=provider.id,
                    provider_model=provider_model.provider_model_name,
                    restrictions=virtual_key.restrictions,
                ):
                    continue
                matches.append(
                    _SubscriptionModelMatch(
                        provider_id=provider.id,
                        provider_model=provider_model.provider_model_name,
                        used_alias=used_alias,
                        priority=project_access.priority,
                    )
                )

    if not matches:
        return None

    match = sorted(matches, key=lambda item: item.priority)[0]
    return ResolvedAccess(
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        virtual_key_id=virtual_key.id,
        provider_id=match.provider_id,
        requested_model=payload.requested_model,
        provider_model=match.provider_model,
        used_alias=match.used_alias,
    )


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


def _model_allowed(provider_model: str, allowed_models: list[str] | None) -> bool:
    if allowed_models is None:
        return True
    return provider_model in allowed_models


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
