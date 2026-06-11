import json
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
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderResourceConflictError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import service
from app.modules.providers.internal.models import (
    CredentialPoolCredential,
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.providers.internal.secret_backends import (
    ProviderSecretBackendRegistry,
    StoredSecret,
)
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ModelMetadataSyncMode,
    ProviderChatCompletionRequest,
    ProviderCredentialRoutingPolicy,
    UpdateProviderCredentialRequest,
    UpdateProviderRequest,
)
from app.modules.providers.schemas import (
    TestModelOfferingRequest as ModelTestRequest,
)


async def _create_actor_scope(db_session: AsyncSession) -> tuple[AuthenticatedUser, Scope]:
    org = Organization(name=f"Routing {uuid4()}", slug=f"routing-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    return actor, Scope(org_id=org.id)


async def _create_provider_with_credentials(
    db_session: AsyncSession,
    *,
    routing_policy: ProviderCredentialRoutingPolicy,
):
    actor, scope = await _create_actor_scope(db_session)
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


class RecordingSecretBackend:
    backend = "local"

    def __init__(self) -> None:
        self.stored: list[tuple[object, str]] = []
        self.resolved_credentials: list[object] = []
        self.deleted_credentials: list[object] = []

    async def store(self, *, credential_id, plaintext):
        self.stored.append((credential_id, plaintext))
        return StoredSecret(
            backend=self.backend,
            reference=f"provider_credentials/{credential_id}/api_key",
            storage_value=f"encrypted::{plaintext}",
        )

    async def resolve(self, *, credential):
        self.resolved_credentials.append(credential.id)
        return credential.api_key_encrypted.removeprefix("encrypted::")

    async def update(self, *, credential, plaintext):
        return await self.store(credential_id=credential.id, plaintext=plaintext)

    async def delete(self, *, credential):
        self.deleted_credentials.append(credential.id)
        credential.api_key_encrypted = None


async def test_provider_credential_uses_secret_backend_for_storage_and_runtime(
    db_session: AsyncSession,
) -> None:
    secret_backend = RecordingSecretBackend()
    secret_registry = ProviderSecretBackendRegistry([secret_backend])
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="First credential", api_key="first-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
        secret_registry=secret_registry,
    )
    credential = await providers_facade.update_provider_credential(
        provider_id=provider.id,
        provider_credential_id=credential.id,
        payload=UpdateProviderCredentialRequest(api_key="updated-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
        secret_registry=secret_registry,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Default"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer updated-secret"
        return httpx.Response(200, json={"id": "chatcmpl_secret_backend"})

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
            secret_registry=secret_registry,
        )

    assert response.body == {"id": "chatcmpl_secret_backend"}
    assert secret_backend.stored == [
        (credential.id, "first-secret"),
        (credential.id, "updated-secret"),
    ]
    assert secret_backend.resolved_credentials == [credential.id]
    assert credential.secret_backend == "local"
    assert credential.secret_reference == f"provider_credentials/{credential.id}/api_key"
    await providers_facade.deactivate_provider_credential(
        provider_id=provider.id,
        provider_credential_id=credential.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    stored_credential = await db_session.get(ProviderCredential, credential.id)
    assert stored_credential is not None
    assert stored_credential.api_key_encrypted == "encrypted::updated-secret"
    assert secret_backend.deleted_credentials == []


async def test_unsupported_secret_backend_fails_without_exposing_secret() -> None:
    credential = ProviderCredential(
        id=uuid4(),
        org_id=uuid4(),
        provider_id=uuid4(),
        name="Unsupported",
        key_prefix="secret-prefix",
        api_key_encrypted="secret-ciphertext",
        secret_backend="unsupported",
        secret_reference="opaque-reference",
    )

    with pytest.raises(ProviderCredentialRequiredError) as exc_info:
        await ProviderSecretBackendRegistry([]).resolve(credential=credential)

    assert "secret-prefix" not in str(exc_info.value)
    assert "secret-ciphertext" not in str(exc_info.value)


async def test_credential_validation_records_success_and_readiness(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="valid-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    before_validation = await providers_facade.get_provider(
        provider_id=provider.id,
        scope=scope,
        db=db_session,
    )
    assert before_validation.readiness.status == "degraded"
    assert before_validation.readiness.is_ready is False

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_provider_credential(
            provider_id=provider.id,
            provider_credential_id=credential.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "valid"
    assert result.last_validation_at is not None
    assert result.last_successful_request_at == result.last_validation_at
    assert result.last_failure_at is None
    assert result.failure_reason is None
    after_validation = await providers_facade.get_provider(
        provider_id=provider.id,
        scope=scope,
        db=db_session,
    )
    assert after_validation.readiness.status == "needs_pool"
    assert after_validation.readiness.is_ready is False


async def test_provider_readiness_requires_clean_active_credential_health(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="invalid-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential_model = await service._get_provider_credential_or_raise(
        provider_id=provider.id,
        provider_credential_id=credential.id,
        scope=scope,
        db=db_session,
    )
    credential_model.health_status = "invalid"
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Default"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    db_session.add(
        ModelOffering(
            org_id=scope.org_id,
            provider_id=provider.id,
            provider_model_name="model-a",
            input_modalities=["text"],
            output_modalities=["text"],
        )
    )
    await db_session.commit()

    readiness = await providers_facade.get_provider(
        provider_id=provider.id,
        scope=scope,
        db=db_session,
    )

    assert readiness.readiness.status == "degraded"
    assert readiness.readiness.is_ready is False


async def test_credential_validation_records_structured_failure(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="invalid-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_provider_credential(
            provider_id=provider.id,
            provider_credential_id=credential.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "invalid"
    assert result.last_validation_at is not None
    assert result.last_failure_at == result.last_validation_at
    assert result.failure_reason == "authentication_failed"
    assert result.failure_message == "Invalid API key"


async def test_provider_resource_conflicts_are_reported_before_database_constraints(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Default"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(ProviderResourceConflictError):
        await providers_facade.add_credential_pool_credential(
            provider_id=provider.id,
            pool_id=pool.id,
            payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="model-a", alias="stable"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(ProviderResourceConflictError):
        await providers_facade.create_model_offering(
            provider_id=provider.id,
            payload=CreateModelOfferingRequest(provider_model_name="model-a"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    with pytest.raises(ProviderResourceConflictError):
        await providers_facade.create_model_offering(
            provider_id=provider.id,
            payload=CreateModelOfferingRequest(provider_model_name="model-b", alias="stable"),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_anthropic_validation_and_model_sync_use_native_auth(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    created = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Anthropic",
            base_url="https://api.anthropic.com/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await db_session.get(Provider, created.id)
    assert provider is not None
    provider.supported_integration = "anthropic_messages"
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="anthropic-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-4-5"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        validation = await providers_facade.test_provider_credential(
            provider_id=provider.id,
            provider_credential_id=credential.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )
        pool = await providers_facade.create_credential_pool(
            provider_id=provider.id,
            payload=CreateCredentialPoolRequest(name="Default"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
        await providers_facade.add_credential_pool_credential(
            provider_id=provider.id,
            pool_id=pool.id,
            payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
            actor=actor,
            scope=scope,
            db=db_session,
        )
        sync = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
        )
        readiness = await providers_facade.get_provider(
            provider_id=provider.id,
            scope=scope,
            db=db_session,
        )

    assert validation.health_status == "valid"
    assert len(requests) == 2
    assert sync.summary.added == 1
    assert sync.models[0].provider_model_name == "claude-sonnet-4-5"
    assert readiness.readiness.status == "ready"
    assert readiness.readiness.is_ready is True


async def test_invalid_anthropic_credential_records_structured_failure(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    created = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Anthropic",
            base_url="https://api.anthropic.com/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await db_session.get(Provider, created.id)
    assert provider is not None
    provider.supported_integration = "anthropic_messages"
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="invalid-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "invalid-secret"
        assert "authorization" not in request.headers
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_provider_credential(
            provider_id=provider.id,
            provider_credential_id=credential.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "invalid"
    assert result.failure_reason == "authentication_failed"
    assert result.failure_message == "invalid x-api-key"


async def test_openai_model_test_uses_chat_completions_with_bearer(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="OpenAI", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="openai-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="gpt-test"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer openai-secret"
        assert json.loads(request.content)["model"] == "gpt-test"
        return httpx.Response(200, json={"id": "chatcmpl-test"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=ModelTestRequest(provider_credential_id=credential.id),
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "valid"
    assert result.provider_credential_id == credential.id
    assert result.upstream_status_code == 200


async def test_anthropic_model_test_uses_native_messages_and_pool_routing(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    created = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Anthropic", base_url="https://api.anthropic.com/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await db_session.get(Provider, created.id)
    assert provider is not None
    provider.supported_integration = "anthropic_messages"
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="anthropic-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Default"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="claude-test"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "claude-test"
        assert body["max_tokens"] == 8
        assert body["messages"] == [{"role": "user", "content": "Reply with ok."}]
        return httpx.Response(200, json={"id": "msg-test", "type": "message"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=ModelTestRequest(credential_pool_id=pool.id),
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "valid"
    assert result.provider_credential_id == credential.id
    assert result.upstream_status_code == 200


async def test_anthropic_model_test_auth_failure_updates_credential_health(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    created = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Anthropic", base_url="https://api.anthropic.com/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await db_session.get(Provider, created.id)
    assert provider is not None
    provider.supported_integration = "anthropic_messages"
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="bad-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="claude-test"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await providers_facade.test_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=ModelTestRequest(provider_credential_id=credential.id),
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    stored = await db_session.get(ProviderCredential, credential.id)
    assert stored is not None
    assert result.health_status == "invalid"
    assert result.upstream_status_code == 401
    assert stored.health_status == "invalid"
    assert stored.failure_reason == "authentication_failed"
    assert stored.failure_message == "invalid x-api-key"


async def test_model_test_returns_controlled_result_for_unsupported_integration(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    created = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Custom", base_url="https://custom.example/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await db_session.get(Provider, created.id)
    assert provider is not None
    provider.supported_integration = "unsupported_test_integration"
    model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="custom-model"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async with httpx.AsyncClient() as http_client:
        result = await providers_facade.test_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=ModelTestRequest(),
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert result.health_status == "unsupported"
    assert result.upstream_status_code is None
    assert result.last_validation_error == (
        "Model testing is not supported for integration 'unsupported_test_integration'."
    )


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


async def test_provider_connection_failure_returns_upstream_error(
    db_session: AsyncSession,
) -> None:
    _actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
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

    assert exc_info.value.status_code == 502
    assert exc_info.value.body == {"error": "provider upstream connection failed"}


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


async def test_legacy_fallback_pool_policy_does_not_retry_next_credential(
    db_session: AsyncSession,
) -> None:
    actor, scope, provider, pool, *_ = await _create_provider_with_credentials(
        db_session,
        routing_policy=ProviderCredentialRoutingPolicy.priority,
    )
    pool.selection_policy = "fallback"
    await db_session.flush()
    seen_authorizations = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["authorization"]
        seen_authorizations.append(authorization)
        if authorization == "Bearer first-secret":
            return httpx.Response(401, json={"error": "bad key"})
        return httpx.Response(200, json={"id": "chatcmpl_legacy_fallback"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
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

    assert exc_info.value.status_code == 401
    assert seen_authorizations == ["Bearer first-secret"]


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


async def test_provider_failure_does_not_route_to_another_provider(
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
    seen_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url).startswith("https://api.example.test"):
            return httpx.Response(502, json={"error": "down"})
        return httpx.Response(200, json={"id": "chatcmpl_provider_fallback"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
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

    assert exc_info.value.status_code == 502
    assert seen_urls == ["https://api.example.test/v1/chat/completions"]


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
