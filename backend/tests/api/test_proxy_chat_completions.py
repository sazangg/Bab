import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.proxy import get_proxy_http_client
from app.core.config import settings
from app.core.security import encrypt, hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import ModelAlias, Project, ProjectProviderAccess, VirtualKey
from app.modules.limits.internal.models import LimitCounter, LimitPolicy
from app.modules.providers.internal.models import Provider
from app.modules.request_logs.internal.models import RequestLog


async def _create_proxy_graph(
    db_session: AsyncSession,
    *,
    raw_key: str = "bab-sk-test-key",
    allowed_models: list[str] | None = None,
    key_restrictions: list[dict[str, object]] | None = None,
) -> tuple[Project, Provider]:
    org = Organization(name="Proxy Org", slug="proxy-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="proxy@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(org_id=org.id, created_by=user.id, name="Inbox Assistant")
    provider = Provider(
        org_id=org.id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted=encrypt("provider-secret"),
        adapter_type="openai_compat",
    )
    db_session.add_all([project, provider])
    await db_session.flush()
    db_session.add(
        ProjectProviderAccess(
            org_id=org.id,
            project_id=project.id,
            provider_id=provider.id,
            allowed_models=allowed_models,
        )
    )
    db_session.add(
        VirtualKey(
            org_id=org.id,
            project_id=project.id,
            name="Local dev",
            key_hash=hash_token(raw_key),
            key_prefix=raw_key[:16],
            restrictions=key_restrictions,
        )
    )
    await db_session.commit()
    return project, provider


async def _create_limit_policy(
    db_session: AsyncSession,
    *,
    org_id,
    scope_type: str,
    scope_id,
    metric: str,
    window: str,
    limit_value: int,
    scope_value: str | None = None,
) -> LimitPolicy:
    policy = LimitPolicy(
        org_id=org_id,
        scope_type=scope_type,
        scope_id=scope_id,
        scope_value=scope_value,
        metric=metric,
        window=window,
        limit_value=limit_value,
    )
    db_session.add(policy)
    await db_session.commit()
    return policy


async def _request_with_mock_upstream(app_client, handler, *, json_body, headers):
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def override_http_client():
        return http_client

    app_client.dependency_overrides[get_proxy_http_client] = override_http_client
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/v1/chat/completions",
                headers=headers,
                json=json_body,
            )
    finally:
        app_client.dependency_overrides.pop(get_proxy_http_client, None)
        await http_client.aclose()


@pytest.mark.asyncio
async def test_proxy_forwards_non_streaming_chat_completion(
    app_client,
    db_session: AsyncSession,
) -> None:
    project, provider = await _create_proxy_graph(db_session, allowed_models=["gpt-5.4-mini"])

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer provider-secret"
        body = request.read()
        assert b'"model":"gpt-5.4-mini"' in body
        assert b'"temperature":0.2' in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_123",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 4,
                    "total_tokens": 13,
                },
            },
        )

    response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={
            "model": "gpt-5.4-mini",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.2,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl_123"
    request_log = await db_session.scalar(select(RequestLog))
    assert request_log is not None
    assert request_log.project_id == project.id
    assert request_log.provider_id == provider.id
    assert request_log.requested_model == "gpt-5.4-mini"
    assert request_log.provider_model == "gpt-5.4-mini"
    assert request_log.http_status == 200
    assert request_log.usage_source == "provider_reported"
    assert request_log.prompt_tokens == 9
    assert request_log.completion_tokens == 4
    assert request_log.total_tokens == 13
    assert request_log.error_code is None


@pytest.mark.asyncio
async def test_proxy_resolves_model_alias_without_provider_header(
    app_client,
    db_session: AsyncSession,
) -> None:
    project, provider = await _create_proxy_graph(db_session, allowed_models=["gpt-5.4-mini"])
    db_session.add(
        ModelAlias(
            org_id=project.org_id,
            alias="fast-default",
            provider_id=provider.id,
            provider_model="gpt-5.4-mini",
        )
    )
    await db_session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert b'"model":"gpt-5.4-mini"' in request.read()
        return httpx.Response(200, json={"id": "chatcmpl_alias"})

    response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={"Authorization": "Bearer bab-sk-test-key"},
        json_body={"model": "fast-default", "messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl_alias"
    request_log = await db_session.scalar(select(RequestLog))
    assert request_log is not None
    assert request_log.usage_source == "estimated"
    assert request_log.total_tokens is not None
    assert request_log.total_tokens > 0


@pytest.mark.asyncio
async def test_proxy_rejects_invalid_virtual_key(app_client, db_session: AsyncSession) -> None:
    _, provider = await _create_proxy_graph(db_session)

    response = await _request_with_mock_upstream(
        app_client,
        lambda _: httpx.Response(500),
        headers={
            "Authorization": "Bearer wrong-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4-mini", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_proxy_rejects_disallowed_model(app_client, db_session: AsyncSession) -> None:
    _, provider = await _create_proxy_graph(db_session, allowed_models=["gpt-5.4-mini"])

    response = await _request_with_mock_upstream(
        app_client,
        lambda _: httpx.Response(500),
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_proxy_passes_through_upstream_error(app_client, db_session: AsyncSession) -> None:
    _, provider = await _create_proxy_graph(db_session, allowed_models=None)

    response = await _request_with_mock_upstream(
        app_client,
        lambda _: httpx.Response(429, json={"error": {"message": "limited"}}),
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 429
    assert response.json() == {"error": {"message": "limited"}}
    assert not response.headers["content-type"].startswith("application/problem+json")
    request_log = await db_session.scalar(select(RequestLog))
    assert request_log is not None
    assert request_log.http_status == 429
    assert request_log.error_code == "provider_upstream_error"


@pytest.mark.asyncio
async def test_proxy_streams_chat_completion_and_records_usage(
    app_client,
    db_session: AsyncSession,
) -> None:
    project, provider = await _create_proxy_graph(db_session, allowed_models=None)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer provider-secret"
        assert b'"stream":true' in request.read()
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=httpx.ByteStream(
                b"".join(
                    [
                        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
                        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
                        (
                            b'data: {"choices":[],"usage":{"prompt_tokens":9,'
                            b'"completion_tokens":4,"total_tokens":13}}\n\n'
                        ),
                        b"data: [DONE]\n\n",
                    ]
                )
            ),
        )

    response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "Hel" in response.text
    assert "data: [DONE]" in response.text
    request_log = await db_session.scalar(select(RequestLog))
    assert request_log is not None
    assert request_log.project_id == project.id
    assert request_log.http_status == 200
    assert request_log.usage_source == "provider_reported"
    assert request_log.prompt_tokens == 9
    assert request_log.completion_tokens == 4
    assert request_log.total_tokens == 13
    assert request_log.error_code is None


@pytest.mark.asyncio
async def test_proxy_rejects_oversized_request_body(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    _, provider = await _create_proxy_graph(db_session, allowed_models=None)
    monkeypatch.setattr(settings, "proxy_max_body_bytes", 10)

    response = await _request_with_mock_upstream(
        app_client,
        lambda _: httpx.Response(500),
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_proxy_enforces_request_count_limit(
    app_client,
    db_session: AsyncSession,
) -> None:
    _, provider = await _create_proxy_graph(
        db_session,
        allowed_models=None,
    )
    await _create_limit_policy(
        db_session,
        org_id=provider.org_id,
        scope_type="provider",
        scope_id=provider.id,
        metric="request_count",
        window="minute",
        limit_value=1,
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "chatcmpl_123"})

    first_response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )
    second_response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    logs = (await db_session.scalars(select(RequestLog).order_by(RequestLog.created_at))).all()
    assert [log.http_status for log in logs] == [200, 429]
    assert logs[-1].error_code == "limit_exceeded"


@pytest.mark.asyncio
async def test_proxy_reserves_and_reconciles_token_limit(
    app_client,
    db_session: AsyncSession,
) -> None:
    project, provider = await _create_proxy_graph(db_session, allowed_models=None)
    await _create_limit_policy(
        db_session,
        org_id=project.org_id,
        scope_type="project",
        scope_id=project.id,
        metric="token_count",
        window="day",
        limit_value=100,
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_123",
                "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
            },
        )

    response = await _request_with_mock_upstream(
        app_client,
        handler,
        headers={
            "Authorization": "Bearer bab-sk-test-key",
            "X-Bab-Provider-Id": str(provider.id),
        },
        json_body={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hi"}]},
    )

    counter = await db_session.scalar(select(LimitCounter))

    assert response.status_code == 200
    assert counter is not None
    assert counter.consumed_amount == 13
