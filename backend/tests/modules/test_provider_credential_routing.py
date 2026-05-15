from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal import service
from app.modules.providers.internal.models import ProviderCredential
from app.modules.providers.schemas import (
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ProviderChatCompletionRequest,
    ProviderCredentialRoutingPolicy,
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
            credential_routing_policy=routing_policy,
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
            priority=10,
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
            priority=20,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return actor, scope, provider, first, second


async def test_priority_routing_uses_lowest_priority_active_credential(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, *_ = await _create_provider_with_credentials(
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
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_priority"}


async def test_least_recently_used_routing_uses_oldest_used_credential(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, first, second = await _create_provider_with_credentials(
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
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_lru"}


async def test_health_based_routing_prefers_valid_credential(db_session: AsyncSession) -> None:
    actor, scope, provider, first, second = await _create_provider_with_credentials(
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
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_health"}


async def test_fallback_routing_retries_next_credential_on_upstream_failure(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, *_ = await _create_provider_with_credentials(
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
            db=db_session,
            http_client=http_client,
        )

    assert seen_authorizations == ["Bearer first-secret", "Bearer second-secret"]
    assert response.body == {"id": "chatcmpl_fallback"}


def test_weighted_routing_uses_priority_as_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    first = ProviderCredential(
        id=uuid4(),
        org_id=uuid4(),
        provider_id=uuid4(),
        name="First",
        key_prefix="firs...",
        api_key_encrypted="first",
        priority=100,
    )
    second = ProviderCredential(
        id=uuid4(),
        org_id=first.org_id,
        provider_id=first.provider_id,
        name="Second",
        key_prefix="seco...",
        api_key_encrypted="second",
        priority=0,
    )

    def choose_last(pool):
        return pool[-1]

    monkeypatch.setattr(service.secrets, "choice", choose_last)

    assert service._weighted_provider_credential_route([first, second])[0] == second


def test_routing_uses_provider_policy_not_credential_policy() -> None:
    provider = type("Provider", (), {"credential_routing_policy": "fallback"})()

    assert service._provider_routing_policy(provider) == ProviderCredentialRoutingPolicy.fallback
