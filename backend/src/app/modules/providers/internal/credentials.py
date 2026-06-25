from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import (
    ProviderNotFoundError,
    ProviderResourceConflictError,
)
from app.modules.providers.internal import credential_routing, repository
from app.modules.providers.internal.adapters import (
    AdapterProvider,
    default_integration_adapter_registry,
)
from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    Provider,
    ProviderCredential,
)
from app.modules.providers.internal.secret_backends import (
    LOCAL_SECRET_BACKEND,
    ProviderSecretBackendRegistry,
    get_default_secret_backend_registry,
)
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateProviderCredentialRequest,
    CredentialPoolCredentialResponse,
    CredentialPoolResponse,
    ProviderCredentialResponse,
    TestProviderCredentialResponse,
    UpdateCredentialPoolCredentialRequest,
    UpdateCredentialPoolRequest,
    UpdateProviderCredentialRequest,
)

logger = structlog.get_logger(__name__)


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


async def _get_provider_credential_or_raise(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredential:
    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if provider_credential is None or provider_credential.provider_id != provider_id:
        raise ProviderNotFoundError
    return provider_credential


async def _get_credential_pool_or_raise(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPool:
    pool = await repository.get_credential_pool(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    if pool is None or pool.provider_id != provider_id:
        raise ProviderNotFoundError
    return pool


async def create_credential_pool(
    *,
    provider_id: UUID,
    payload: CreateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        pool = await repository.create_credential_pool(
            org_id=scope.org_id,
            provider_id=provider_id,
            name=payload.name,
            description=payload.description,
            selection_policy=payload.selection_policy,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool.created",
            message=f"Created credential pool {pool.name}.",
            provider_id=provider_id,
            pool_id=pool.id,
            db=db,
        )
    logger.info(
        "credential_pool_created",
        provider_id=str(provider_id),
        pool_id=str(pool.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _credential_pool_response(pool)


async def list_credential_pools(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    pools = await repository.list_credential_pools(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    counts: dict[UUID, tuple[int, int]] = {}
    for pool in pools:
        rows = await repository.list_pool_credentials(org_id=scope.org_id, pool_id=pool.id, db=db)
        active_count = sum(
            1 for membership, credential in rows if membership.is_active and credential.is_active
        )
        counts[pool.id] = (len(rows), active_count)
    return [
        _credential_pool_response(
            pool,
            credential_count=counts.get(pool.id, (0, 0))[0],
            active_credential_count=counts.get(pool.id, (0, 0))[1],
        )
        for pool in pools
    ]


async def get_credential_pool(
    *,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    pool = await repository.get_credential_pool(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    if pool is None:
        raise ProviderNotFoundError
    return _credential_pool_response(pool)


async def update_credential_pool(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: UpdateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        pool = await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        if payload.name is not None:
            pool.name = payload.name
        if "description" in payload.model_fields_set:
            pool.description = payload.description
        if payload.selection_policy is not None:
            pool.selection_policy = payload.selection_policy
        if payload.is_active is not None:
            pool.is_active = payload.is_active
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool.updated",
            message=f"Updated credential pool {pool.name}.",
            provider_id=provider_id,
            pool_id=pool.id,
            db=db,
        )
    logger.info(
        "credential_pool_updated",
        provider_id=str(provider_id),
        pool_id=str(pool.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _credential_pool_response(pool)


async def list_credential_pool_credentials(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolCredentialResponse]:
    await _get_credential_pool_or_raise(
        provider_id=provider_id,
        pool_id=pool_id,
        scope=scope,
        db=db,
    )
    rows = await repository.list_pool_credentials(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    return [_pool_credential_response(membership, credential) for membership, credential in rows]


async def add_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: AddCredentialPoolCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolCredentialResponse:
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=payload.provider_credential_id,
            scope=scope,
            db=db,
        )
        existing_memberships = await repository.list_pool_credentials(
            org_id=scope.org_id,
            pool_id=pool_id,
            db=db,
        )
        if any(
            membership.provider_credential_id == payload.provider_credential_id
            for membership, _credential in existing_memberships
        ):
            raise ProviderResourceConflictError
        membership = await repository.create_pool_credential(
            org_id=scope.org_id,
            pool_id=pool_id,
            provider_credential_id=payload.provider_credential_id,
            priority=payload.priority,
            weight=payload.weight,
            is_active=payload.is_active,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.added",
            message=f"Added credential {credential.name} to credential pool.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"provider_credential_id": str(payload.provider_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_added",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        provider_credential_id=str(payload.provider_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _pool_credential_response(membership, credential)


async def update_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    payload: UpdateCredentialPoolCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolCredentialResponse:
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        membership = await repository.get_pool_credential(
            org_id=scope.org_id,
            pool_credential_id=pool_credential_id,
            db=db,
        )
        if membership is None or membership.pool_id != pool_id:
            raise ProviderNotFoundError
        if payload.priority is not None:
            membership.priority = payload.priority
        if payload.weight is not None:
            membership.weight = payload.weight
        if payload.is_active is not None:
            membership.is_active = payload.is_active
        credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=membership.provider_credential_id,
            scope=scope,
            db=db,
        )
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.updated",
            message=f"Updated pool membership for credential {credential.name}.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"pool_credential_id": str(pool_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_updated",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        pool_credential_id=str(pool_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _pool_credential_response(membership, credential)


async def delete_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        membership = await repository.get_pool_credential(
            org_id=scope.org_id,
            pool_credential_id=pool_credential_id,
            db=db,
        )
        if membership is None or membership.pool_id != pool_id:
            raise ProviderNotFoundError
        await repository.delete_pool_credential(pool_credential=membership, db=db)
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.removed",
            message="Removed credential from credential pool.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"pool_credential_id": str(pool_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_deleted",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        pool_credential_id=str(pool_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


async def create_provider_credential(
    *,
    provider_id: UUID,
    payload: CreateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderCredentialResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        api_key = _normalize_api_key(payload.api_key)
        provider_credential_id = uuid4()
        registry = secret_registry or get_default_secret_backend_registry()
        backend = registry.get(LOCAL_SECRET_BACKEND)
        stored_secret = await backend.store(
            credential_id=provider_credential_id,
            plaintext=api_key,
        )
        provider_credential = await repository.create_provider_credential(
            provider_credential_id=provider_credential_id,
            org_id=scope.org_id,
            provider_id=provider_id,
            created_by=actor.id,
            name=payload.name,
            key_prefix=_key_prefix(api_key),
            api_key_encrypted=stored_secret.storage_value,
            secret_backend=stored_secret.backend,
            secret_reference=stored_secret.reference,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.created",
            message=f"Created provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
            db=db,
        )
    return ProviderCredentialResponse.model_validate(provider_credential)


async def list_provider_credentials(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredentialResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    provider_credentials = await repository.list_provider_credentials(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    return [
        ProviderCredentialResponse.model_validate(provider_credential)
        for provider_credential in provider_credentials
    ]


async def get_provider_credential(
    *,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if provider_credential is None:
        raise ProviderNotFoundError
    return ProviderCredentialResponse.model_validate(provider_credential)


async def update_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    payload: UpdateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderCredentialResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        if payload.name is not None:
            provider_credential.name = payload.name
        if payload.api_key is not None:
            api_key = _normalize_api_key(payload.api_key)
            registry = secret_registry or get_default_secret_backend_registry()
            backend = registry.get(provider_credential.secret_backend)
            stored_secret = await backend.update(
                credential=provider_credential,
                plaintext=api_key,
            )
            provider_credential.key_prefix = _key_prefix(api_key)
            provider_credential.api_key_encrypted = stored_secret.storage_value
            provider_credential.secret_backend = stored_secret.backend
            provider_credential.secret_reference = stored_secret.reference
            provider_credential.health_status = "unchecked"
            provider_credential.last_validation_error = None
            provider_credential.last_validation_at = None
            provider_credential.last_failure_at = None
            provider_credential.failure_reason = None
            provider_credential.failure_message = None
        if payload.is_active is not None:
            provider_credential.is_active = payload.is_active

        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.updated",
            message=f"Updated provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
            db=db,
        )

    return ProviderCredentialResponse.model_validate(provider_credential)


async def test_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> TestProviderCredentialResponse:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        try:
            adapter = default_integration_adapter_registry.get(provider.supported_integration)
            await adapter.list_models(
                provider=AdapterProvider(
                    base_url=provider.base_url,
                    api_key=await (
                        secret_registry or get_default_secret_backend_registry()
                    ).resolve(credential=provider_credential),
                ),
                http_client=http_client,
            )
            validated_at = repository.datetime_now()
            provider_credential.health_status = "valid"
            provider_credential.last_validation_error = None
            provider_credential.last_validation_at = validated_at
            provider_credential.last_successful_request_at = validated_at
            provider_credential.failure_reason = None
            provider_credential.failure_message = None
            health_status = "valid"
            error = None
            last_successful_request_at = provider_credential.last_successful_request_at
        except Exception as exc:  # noqa: BLE001 - persisted as upstream credential health.
            failure_message = await credential_routing.mark_provider_credential_validation_failed(
                provider_credential=provider_credential,
                error=exc,
                db=db,
            )
            health_status = "invalid"
            error = failure_message
            last_successful_request_at = provider_credential.last_successful_request_at

    return TestProviderCredentialResponse(
        id=provider_credential.id,
        health_status=health_status,
        last_validation_error=error,
        last_validation_at=provider_credential.last_validation_at,
        last_successful_request_at=last_successful_request_at,
        last_failure_at=provider_credential.last_failure_at,
        failure_reason=provider_credential.failure_reason,
        failure_message=provider_credential.failure_message,
    )


async def deactivate_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        provider_credential.is_active = False
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.deactivated",
            message=f"Deactivated provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
            db=db,
        )


def _credential_pool_response(
    pool: CredentialPool,
    *,
    credential_count: int = 0,
    active_credential_count: int = 0,
) -> CredentialPoolResponse:
    return CredentialPoolResponse(
        id=pool.id,
        org_id=pool.org_id,
        provider_id=pool.provider_id,
        name=pool.name,
        description=pool.description,
        selection_policy=pool.selection_policy,
        is_active=pool.is_active,
        credential_count=credential_count,
        active_credential_count=active_credential_count,
        created_at=pool.created_at,
        updated_at=pool.updated_at,
    )


def _pool_credential_response(
    membership: CredentialPoolCredential,
    credential: ProviderCredential,
) -> CredentialPoolCredentialResponse:
    return CredentialPoolCredentialResponse(
        id=membership.id,
        org_id=membership.org_id,
        pool_id=membership.pool_id,
        provider_credential_id=membership.provider_credential_id,
        priority=membership.priority,
        weight=membership.weight,
        is_active=membership.is_active,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
        credential=ProviderCredentialResponse.model_validate(credential),
    )


def _key_prefix(api_key: str) -> str:
    return f"{api_key[:4]}..."


def _normalize_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if normalized.lower().startswith("bearer "):
        normalized = normalized[7:].strip()
    return normalized
