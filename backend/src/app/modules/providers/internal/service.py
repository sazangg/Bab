from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import encrypt
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.providers.internal import repository
from app.modules.providers.internal.models import Provider
from app.modules.providers.schemas import (
    CreateProviderRequest,
    ProviderResponse,
    UpdateProviderRequest,
)

logger = structlog.get_logger(__name__)


async def create_provider(
    *,
    payload: CreateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    async with transaction(db):
        provider = await repository.create_provider(
            org_id=scope.org_id,
            name=payload.name,
            base_url=str(payload.base_url).rstrip("/"),
            api_key_encrypted=encrypt(payload.api_key),
            adapter_type=payload.adapter_type,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.created",
                target_type="provider",
                target_id=provider.id,
                event_metadata={"name": provider.name},
            ),
            db,
        )

    logger.info("provider_created", provider_id=str(provider.id), org_id=str(scope.org_id))
    return _to_response(provider)


async def list_providers(*, scope: Scope, db: AsyncSession) -> list[ProviderResponse]:
    providers = await repository.list_providers(org_id=scope.org_id, db=db)
    return [_to_response(provider) for provider in providers]


async def get_provider(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> ProviderResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    return _to_response(provider)


async def update_provider(
    *,
    provider_id: UUID,
    payload: UpdateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        credential_changed = payload.api_key is not None

        if payload.name is not None:
            provider.name = payload.name
        if payload.base_url is not None:
            provider.base_url = str(payload.base_url).rstrip("/")
        if payload.adapter_type is not None:
            provider.adapter_type = payload.adapter_type
        if payload.is_active is not None:
            provider.is_active = payload.is_active
        if payload.api_key is not None:
            provider.api_key_encrypted = encrypt(payload.api_key)

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.updated",
                target_type="provider",
                target_id=provider.id,
            ),
            db,
        )
        if credential_changed:
            await audit_facade.record_event(
                RecordAuditEvent(
                    org_id=scope.org_id,
                    actor_user_id=actor.id,
                    event="provider.credential_changed",
                    target_type="provider",
                    target_id=provider.id,
                ),
                db,
            )

    logger.info("provider_updated", provider_id=str(provider.id), org_id=str(scope.org_id))
    return _to_response(provider)


async def deactivate_provider(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.deactivated",
                target_type="provider",
                target_id=provider.id,
            ),
            db,
        )

    logger.info("provider_deactivated", provider_id=str(provider_id), org_id=str(scope.org_id))


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


def _to_response(provider: Provider) -> ProviderResponse:
    return ProviderResponse.model_validate(provider)
