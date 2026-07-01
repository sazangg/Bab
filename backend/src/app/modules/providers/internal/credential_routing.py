import secrets
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import SecurityError
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import repository
from app.modules.providers.internal.models import (
    CredentialPoolCredential,
    Provider,
    ProviderCredential,
)
from app.modules.providers.internal.secret_backends import (
    ProviderSecretBackendRegistry,
    get_default_secret_backend_registry,
    resolve_legacy_provider_secret,
)
from app.modules.providers.schemas import ProviderCredentialRoutingPolicy


async def resolve_provider_credential_route(
    *,
    provider: Provider,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredential | None]:
    if provider_credential_id is None:
        if pool_id is not None:
            pool = await repository.get_credential_pool(
                org_id=scope.org_id,
                pool_id=pool_id,
                db=db,
            )
            if pool is None or pool.provider_id != provider.id:
                raise ProviderNotFoundError
            if not pool.is_active:
                raise ProviderCredentialRequiredError
            pool_credentials = await repository.list_pool_credentials(
                org_id=scope.org_id,
                pool_id=pool_id,
                db=db,
            )
            routing_policy = _credential_routing_policy(pool.selection_policy)
            active_pool_credentials = [
                (membership, credential)
                for membership, credential in pool_credentials
                if membership.is_active and credential.is_active
            ]
            if active_pool_credentials:
                routed = _route_pool_credentials(
                    active_pool_credentials,
                    routing_policy=routing_policy,
                )
                if routed and routing_policy in {
                    ProviderCredentialRoutingPolicy.round_robin,
                    ProviderCredentialRoutingPolicy.least_recently_used,
                }:
                    # Stamp selection time so rapid/concurrent requests rotate across the
                    # pool instead of all landing on the same least-recently-used
                    # credential (the timestamp previously only advanced on success).
                    routed[0].last_used_at = repository.datetime_now()
                    await db.flush()
                return routed
            raise ProviderCredentialRequiredError

        provider_credentials = await repository.list_provider_credentials(
            org_id=scope.org_id,
            provider_id=provider.id,
            db=db,
        )
        active_credentials = [
            credential for credential in provider_credentials if credential.is_active
        ]
        if active_credentials:
            return sorted(active_credentials, key=lambda credential: credential.created_at)
        if provider.api_key_encrypted is not None:
            return [None]
        raise ProviderCredentialRequiredError

    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if (
        provider_credential is None
        or provider_credential.provider_id != provider.id
        or not provider_credential.is_active
    ):
        raise ProviderNotFoundError

    return [provider_credential]


async def api_key_for_routed_credential(
    *,
    provider: Provider,
    credential: ProviderCredential | None,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> str:
    try:
        if credential is None:
            return await resolve_legacy_provider_secret(provider=provider)
        return await (secret_registry or get_default_secret_backend_registry()).resolve(
            credential=credential
        )
    except SecurityError as exc:
        # An unreadable ciphertext (rotated/restored encryption key, corruption) becomes
        # a credential failure rather than an uncaught 500: this keeps the multi-credential
        # fallback loop alive and lets credential health reflect the problem.
        raise ProviderUpstreamError(
            status_code=502,
            body={
                "error": {
                    "message": "provider credential could not be decrypted",
                    "type": "credential_error",
                }
            },
            failure_reason="credential_error",
        ) from exc


async def mark_provider_credential_failed(
    *,
    provider_credential: ProviderCredential,
    error: ProviderUpstreamError,
    db: AsyncSession,
) -> None:
    failed_at = repository.datetime_now()
    failure_reason, failure_message = _credential_failure_details(error)
    provider_credential.health_status = "invalid" if error.status_code in {401, 403} else "degraded"
    provider_credential.last_validation_error = failure_message
    provider_credential.last_failure_at = failed_at
    provider_credential.failure_reason = failure_reason
    provider_credential.failure_message = failure_message
    await db.flush()


async def mark_provider_credential_validation_failed(
    *,
    provider_credential: ProviderCredential,
    error: Exception,
    db: AsyncSession,
) -> str:
    validated_at = repository.datetime_now()
    failure_reason, failure_message = _credential_failure_details(error)
    provider_credential.health_status = "invalid"
    provider_credential.last_validation_error = failure_message
    provider_credential.last_validation_at = validated_at
    provider_credential.last_failure_at = validated_at
    provider_credential.failure_reason = failure_reason
    provider_credential.failure_message = failure_message
    await db.flush()
    return failure_message


def should_try_next_credential(error: ProviderUpstreamError) -> bool:
    if error.failure_reason in {"connection_failed", "timeout"}:
        return False
    return error.status_code in {401, 403, 408, 409, 429, 500, 502, 503, 504}


def _route_pool_credentials(
    pool_credentials: list[tuple[CredentialPoolCredential, ProviderCredential]],
    *,
    routing_policy: ProviderCredentialRoutingPolicy,
) -> list[ProviderCredential]:
    ordered = sorted(pool_credentials, key=_pool_credential_priority_key)
    if routing_policy == ProviderCredentialRoutingPolicy.priority:
        return [ordered[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.round_robin:
        return [sorted(pool_credentials, key=_pool_credential_lru_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.least_recently_used:
        return [sorted(pool_credentials, key=_pool_credential_lru_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.health_based:
        return [sorted(pool_credentials, key=_pool_credential_health_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.weighted:
        return [_weighted_pool_credential_route(pool_credentials)[0]]
    return [credential for _, credential in ordered]


def _credential_routing_policy(value: str) -> ProviderCredentialRoutingPolicy:
    try:
        return ProviderCredentialRoutingPolicy(value)
    except ValueError:
        return ProviderCredentialRoutingPolicy.priority


def _pool_credential_priority_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[int, datetime]:
    membership, credential = item
    return (membership.priority, membership.created_at, credential.created_at)


def _pool_credential_lru_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[datetime, int, datetime]:
    membership, credential = item
    return (
        credential.last_used_at or datetime.min.replace(tzinfo=UTC),
        membership.priority,
        credential.created_at,
    )


def _pool_credential_health_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[int, int, datetime]:
    membership, credential = item
    health_rank = {
        "valid": 0,
        "unchecked": 1,
        "degraded": 2,
        "invalid": 3,
    }.get(credential.health_status, 2)
    return (health_rank, membership.priority, credential.created_at)


def _weighted_pool_credential_route(
    pool_credentials: list[tuple[CredentialPoolCredential, ProviderCredential]],
) -> list[ProviderCredential]:
    weighted_pool: list[tuple[CredentialPoolCredential, ProviderCredential]] = []
    for item in pool_credentials:
        membership, _credential = item
        weighted_pool.extend([item] * max(1, membership.weight))
    selected_membership, selected = secrets.choice(weighted_pool)
    rest = [
        credential
        for membership, credential in sorted(pool_credentials, key=_pool_credential_priority_key)
        if membership.id != selected_membership.id
    ]
    return [selected, *rest]


def _credential_failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderUpstreamError):
        if error.failure_reason in {
            "connection_failed",
            "credential_error",
            "rate_limited",
            "timeout",
        }:
            reason = error.failure_reason
        elif error.status_code in {401, 403}:
            reason = "authentication_failed"
        elif error.failure_reason == "provider_5xx":
            reason = "upstream_unavailable"
        else:
            reason = "upstream_error"
        return reason, _upstream_error_message(error)
    if isinstance(error, TimeoutError):
        return "timeout", "Provider validation timed out."
    if isinstance(error, httpx.HTTPError):
        return "connection_failed", "Could not connect to the provider."
    return "validation_failed", str(error) or "Provider credential validation failed."


def _upstream_error_message(error: ProviderUpstreamError) -> str:
    body = error.body
    if isinstance(body, dict):
        detail = body.get("error")
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"]
        if isinstance(detail, str):
            return detail
    return f"Provider returned HTTP {error.status_code}."
