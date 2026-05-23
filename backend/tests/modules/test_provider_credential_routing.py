from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.proxy import _enforce_provider_body_size
from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.providers.internal import service
from app.modules.providers.internal.models import CredentialPoolCredential, ProviderCredential
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ProviderChatCompletionRequest,
    ProviderCredentialRoutingPolicy,
    UpdateProviderRequest,
)


async def _create_provider_with_credentials(
    db_session: AsyncSession,
    *,
    routing_policy: ProviderCredentialRoutingPolicy,
):
    org = Organization(name=f"Routing {uuid4()}", slug=f"routing-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.example.test/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    first = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(
            name="First",
            api_key="first-secret",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    second = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(
            name="Second",
            api_key="second-secret",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Routing", selection_policy=routing_policy),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(
            provider_credential_id=first.id,
            priority=10,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(
            provider_credential_id=second.id,
            priority=20,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return actor, scope, provider, pool, first, second


async def test_priority_routing_uses_lowest_priority_active_credential(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer first-secret"
        return httpx.Response(200, json={"id": "chatcmpl_priority"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_priority"}


async def test_least_recently_used_routing_uses_oldest_used_credential(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, first, second = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.least_recently_used,
    )
    first_model = await service._get_provider_credential_or_raise(
        provider_id=provider.id,
        provider_credential_id=first.id,
        scope=scope,
        db=db_session,
    )
    second_model = await service._get_provider_credential_or_raise(
        provider_id=provider.id,
        provider_credential_id=second.id,
        scope=scope,
        db=db_session,
    )
    first_model.last_used_at = datetime.now(UTC)
    second_model.last_used_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer second-secret"
        return httpx.Response(200, json={"id": "chatcmpl_lru"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_lru"}


async def test_health_based_routing_prefers_valid_credential(db_session: AsyncSession) -> None:
    actor, scope, provider, pool, first, second = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.health_based,
    )
    first_model = await service._get_provider_credential_or_raise(
        provider_id=provider.id,
        provider_credential_id=first.id,
        scope=scope,
        db=db_session,
    )
    second_model = await service._get_provider_credential_or_raise(
        provider_id=provider.id,
        provider_credential_id=second.id,
        scope=scope,
        db=db_session,
    )
    first_model.health_status = "invalid"
    second_model.health_status = "valid"
    await db_session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer second-secret"
        return httpx.Response(200, json={"id": "chatcmpl_health"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_health"}


async def test_fallback_routing_retries_next_credential_on_upstream_failure(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.fallback,
    )
    seen_authorizations = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["authorization"]
        seen_authorizations.append(authorization)
        if authorization == "Bearer first-secret":
            return httpx.Response(401, json={"error": "bad key"})
        return httpx.Response(200, json={"id": "chatcmpl_fallback"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert seen_authorizations == ["Bearer first-secret", "Bearer second-secret"]
    assert response.body == {"id": "chatcmpl_fallback"}


def test_weighted_routing_uses_membership_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    first = ProviderCredential(
        id=uuid4(),
        org_id=uuid4(),
        provider_id=uuid4(),
        name="First",
        key_prefix="firs...",
        api_key_encrypted="first",
    )
    second = ProviderCredential(
        id=uuid4(),
        org_id=first.org_id,
        provider_id=first.provider_id,
        name="Second",
        key_prefix="seco...",
        api_key_encrypted="second",
    )
    first_membership = CredentialPoolCredential(
        id=uuid4(),
        org_id=first.org_id,
        pool_id=uuid4(),
        provider_credential_id=first.id,
        priority=10,
        weight=1,
    )
    second_membership = CredentialPoolCredential(
        id=uuid4(),
        org_id=first.org_id,
        pool_id=first_membership.pool_id,
        provider_credential_id=second.id,
        priority=20,
        weight=10,
    )

    def choose_last(pool):
        return pool[-1]

    monkeypatch.setattr(service.secrets, "choice", choose_last)

    assert (
        service._weighted_pool_credential_route(
            [(first_membership, first), (second_membership, second)]
        )[0]
        == second
    )


async def test_retry_policy_retries_retryable_upstream_status(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )
    await providers_facade.update_provider(
        provider_id=provider.id,
        payload=UpdateProviderRequest(
            retry_policy={
                "enabled": True,
                "max_attempts": 2,
                "backoff": "constant",
                "initial_delay_ms": 0,
                "max_delay_ms": 0,
                "retry_on_status": [500],
            },
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(200, json={"id": "chatcmpl_retry"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert attempts == 2
    assert response.body == {"id": "chatcmpl_retry"}


async def test_fallback_policy_uses_configured_provider_after_failure(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )
    fallback_provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Fallback",
            base_url="https://fallback.example.test/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=fallback_provider.id,
        payload=CreateProviderCredentialRequest(
            name="Fallback credential",
            api_key="fallback-secret",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.update_provider(
        provider_id=provider.id,
        payload=UpdateProviderRequest(
            fallback_policy={
                "enabled": True,
                "trigger_on_status": [502],
                "fallback_provider_ids": [str(fallback_provider.id)],
            },
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    seen_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url).startswith("https://api.example.test"):
            return httpx.Response(502, json={"error": "down"})
        assert request.headers["authorization"] == "Bearer fallback-secret"
        return httpx.Response(200, json={"id": "chatcmpl_provider_fallback"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )

    assert seen_urls == [
        "https://api.example.test/v1/chat/completions",
        "https://fallback.example.test/v1/chat/completions",
    ]
    assert response.body == {"id": "chatcmpl_provider_fallback"}


async def test_circuit_breaker_opens_after_configured_failure_rate(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )
    await providers_facade.update_provider(
        provider_id=provider.id,
        payload=UpdateProviderRequest(
            circuit_breaker_policy={
                "enabled": True,
                "failure_threshold_pct": 50,
                "min_request_count": 2,
                "window_seconds": 60,
                "cooldown_seconds": 30,
            },
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(200, json={"id": "chatcmpl_success"})
        return httpx.Response(500, json={"error": "down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await providers_facade.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=scope,
            pool_id=pool.id,
            db=db_session,
            http_client=http_client,
        )
        with pytest.raises(ProviderUpstreamError):
            await providers_facade.create_chat_completion(
                provider_id=provider.id,
                payload=ProviderChatCompletionRequest(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": "Hello"}],
                ),
                scope=scope,
                pool_id=pool.id,
                db=db_session,
                http_client=http_client,
            )
        with pytest.raises(ProviderUpstreamError) as exc_info:
            await providers_facade.create_chat_completion(
                provider_id=provider.id,
                payload=ProviderChatCompletionRequest(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": "Hello"}],
                ),
                scope=scope,
                pool_id=pool.id,
                db=db_session,
                http_client=http_client,
            )

    assert attempts == 2
    assert exc_info.value.status_code == 503
    assert exc_info.value.body == {"error": "provider circuit is open"}


def test_provider_concurrency_slot_tracks_limit_changes() -> None:
    provider = type(
        "Provider",
        (),
        {"id": uuid4(), "max_concurrent_requests": 1},
    )()

    first_slot = service._provider_concurrency_slot(provider)
    provider.max_concurrent_requests = 2
    second_slot = service._provider_concurrency_slot(provider)

    assert first_slot is not second_slot


def test_provider_body_size_guard_rejects_oversized_payloads() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _enforce_provider_body_size(b"too-large", max_body_bytes=3)

    assert exc_info.value.status_code == 413
