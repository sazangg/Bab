from collections.abc import AsyncGenerator
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.routes.proxy import get_proxy_http_client
from app.core.bootstrap import sync_default_workspace
from app.core.config import settings
from app.core.migrations import run_database_migrations
from app.modules.keys import facade as keys_facade
from app.modules.keys.schemas import ResolveAccessRequest


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": settings.default_admin_email,
            "password": settings.default_admin_password,
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _provision_gateway_path(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    upstream_api_key: str = "sk-test-upstream",
    model: str = "gpt-test",
    key_payload: dict | None = None,
    limit_payload: dict | None = None,
) -> tuple[str, str, str]:
    providers = (await client.get("/api/v1/providers", headers=headers)).json()
    provider = next(provider for provider in providers if provider["slug"] == "openai")
    provider_id = provider["id"]

    credential_response = await client.post(
        f"/api/v1/providers/{provider_id}/credentials",
        headers=headers,
        json={"name": "Integration OpenAI key", "api_key": upstream_api_key},
    )
    assert credential_response.status_code == 201
    credential_id = credential_response.json()["id"]

    pool_response = await client.post(
        f"/api/v1/providers/{provider_id}/pools",
        headers=headers,
        json={"name": "Integration pool", "selection_policy": "priority"},
    )
    assert pool_response.status_code == 201
    pool_id = pool_response.json()["id"]

    pool_credential_response = await client.post(
        f"/api/v1/providers/{provider_id}/pools/{pool_id}/credentials",
        headers=headers,
        json={"provider_credential_id": credential_id, "priority": 100, "weight": 1},
    )
    assert pool_credential_response.status_code == 201

    offering_response = await client.post(
        f"/api/v1/providers/{provider_id}/offerings",
        headers=headers,
        json={
            "provider_model_name": model,
            "alias": model,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": {"chat": True, "streaming": True},
            "input_price_per_million_tokens": 100,
            "output_price_per_million_tokens": 200,
        },
    )
    assert offering_response.status_code == 201
    offering_id = offering_response.json()["id"]

    team_response = await client.post(
        "/api/v1/teams",
        headers=headers,
        json={"name": "Integration Team", "slug": "integration-team"},
    )
    assert team_response.status_code == 201
    team_id = team_response.json()["id"]

    project_response = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        headers=headers,
        json={"name": "Integration Project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    access_response = await client.post(
        "/api/v1/policies/access",
        headers=headers,
        json={
            "name": "Integration access",
            "routes": [
                {
                    "provider_id": provider_id,
                    "credential_pool_id": pool_id,
                    "model_offering_ids": [offering_id],
                }
            ],
        },
    )
    assert access_response.status_code == 201
    access_policy_id = access_response.json()["id"]

    limit_response = await client.post(
        "/api/v1/policies/limits",
        headers=headers,
        json={
            "name": "Integration limits",
            "budget_cents": 1000,
            "max_requests": 10,
            "window": "monthly",
            **(limit_payload or {}),
        },
    )
    assert limit_response.status_code == 201
    limit_policy_id = limit_response.json()["id"]

    for payload in (
        {
            "policy_type": "access",
            "access_policy_id": access_policy_id,
            "scope_type": "project",
            "project_id": project_id,
        },
        {
            "policy_type": "limit",
            "limit_policy_id": limit_policy_id,
            "scope_type": "project",
            "project_id": project_id,
        },
    ):
        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json=payload,
        )
        assert assignment_response.status_code == 201

    key_response = await client.post(
        f"/api/v1/projects/{project_id}/keys",
        headers=headers,
        json={"name": "Integration key", **(key_payload or {})},
    )
    assert key_response.status_code == 201
    virtual_key = key_response.json()["key"]
    assert virtual_key is not None
    return virtual_key, credential_id, provider_id


@pytest.mark.asyncio
async def test_migrations_create_current_schema(tmp_path) -> None:
    database_path = tmp_path / "migration-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    await run_database_migrations(engine)

    async with engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )

    await engine.dispose()

    assert "alembic_version" in table_names
    assert "provider_credentials" in table_names
    assert "credential_pool_credentials" in table_names
    assert "usage_records" in table_names


@pytest.mark.asyncio
async def test_gateway_path_records_usage_with_mocked_upstream(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"].startswith("Bearer sk-test-upstream")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-integration",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from upstream."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                },
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
        )

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )
        assert proxy_response.status_code == 200
        assert proxy_response.headers["x-request-id"]
        assert proxy_response.json()["id"] == "chatcmpl-integration"

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        records = usage_response.json()
        assert len(records) == 1
        assert records[0]["requested_model"] == "gpt-test"
        assert records[0]["provider_model"] == "gpt-test"
        assert records[0]["provider_credential_id"] == credential_id
        assert records[0]["provider_credential_name"] == "Integration OpenAI key"
        assert records[0]["request_id"] == proxy_response.headers["x-request-id"]
        assert records[0]["http_status"] == 200
        assert records[0]["total_tokens"] == 17

        export_response = await client.get(
            "/api/v1/usage/records/export",
            params={"model": "gpt-test"},
            headers=admin_headers,
        )
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("text/csv")
        assert "gpt-test" in export_response.text
        assert proxy_response.headers["x-request-id"] in export_response.text


@pytest.mark.asyncio
async def test_project_key_creation_without_limit_policy_succeeds(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        providers = (await client.get("/api/v1/providers", headers=admin_headers)).json()
        provider = next(provider for provider in providers if provider["slug"] == "openai")
        provider_id = provider["id"]

        pool_response = await client.post(
            f"/api/v1/providers/{provider_id}/pools",
            headers=admin_headers,
            json={"name": "Access-only pool", "selection_policy": "priority"},
        )
        assert pool_response.status_code == 201
        pool_id = pool_response.json()["id"]

        offering_response = await client.post(
            f"/api/v1/providers/{provider_id}/offerings",
            headers=admin_headers,
            json={"provider_model_name": "gpt-access-only", "alias": "gpt-access-only"},
        )
        assert offering_response.status_code == 201
        offering_id = offering_response.json()["id"]

        team_response = await client.post(
            "/api/v1/teams",
            headers=admin_headers,
            json={"name": "Access Only Team", "slug": "access-only-team"},
        )
        assert team_response.status_code == 201
        team_id = team_response.json()["id"]

        project_response = await client.post(
            f"/api/v1/teams/{team_id}/projects",
            headers=admin_headers,
            json={"name": "Access Only Project"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        access_response = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Access without limits",
                "routes": [
                    {
                        "provider_id": provider_id,
                        "credential_pool_id": pool_id,
                        "model_offering_ids": [offering_id],
                    }
                ],
            },
        )
        assert access_response.status_code == 201

        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "access_policy_id": access_response.json()["id"],
                "scope_type": "project",
                "project_id": project_id,
            },
        )
        assert assignment_response.status_code == 201

        key_response = await client.post(
            f"/api/v1/projects/{project_id}/keys",
            headers=admin_headers,
            json={"name": "Access-only key"},
        )

    assert key_response.status_code == 201
    virtual_key = key_response.json()["key"]
    assert virtual_key is not None

    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(
            raw_key=virtual_key,
            requested_model="gpt-access-only",
        ),
        db=db_session,
    )

    assert resolved.provider_id == UUID(provider_id)
    assert resolved.pool_id == UUID(pool_id)
    assert resolved.provider_model == "gpt-access-only"
    assert resolved.limit_policies == []


@pytest.mark.asyncio
async def test_gateway_enforces_virtual_key_request_rate_limit(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-key-limit",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
            limit_payload={"max_requests": 2, "window": "daily"},
        )

        payload = {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Say hello."}],
        }
        first_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json=payload,
        )
        assert first_response.status_code == 200

        second_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json=payload,
        )
        assert second_response.status_code == 200

        limited_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json=payload,
        )
        assert limited_response.status_code == 403
        assert limited_response.json()["detail"] == "limit policy request limit exceeded"


@pytest.mark.asyncio
async def test_gateway_proxy_does_not_cross_provider_fallback(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fallback.example":
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-fallback",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "fallback"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        return httpx.Response(500, json={"error": {"message": "primary failed"}})

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, provider_id = await _provision_gateway_path(
            client,
            admin_headers,
        )
        fallback_provider = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Fallback provider",
                "slug": "fallback-provider",
                "base_url": "https://fallback.example/v1",
                "capabilities": {"chat": True},
            },
        )
        assert fallback_provider.status_code == 201
        fallback_provider_id = fallback_provider.json()["id"]
        fallback_credential = await client.post(
            f"/api/v1/providers/{fallback_provider_id}/credentials",
            headers=admin_headers,
            json={"name": "Fallback key", "api_key": "sk-fallback"},
        )
        assert fallback_credential.status_code == 201
        update_provider = await client.patch(
            f"/api/v1/providers/{provider_id}",
            headers=admin_headers,
            json={
                "fallback_policy": {
                    "enabled": True,
                    "fallback_provider_ids": [fallback_provider_id],
                    "trigger_on_status": [500],
                }
            },
        )
        assert update_provider.status_code == 200

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}", "X-Request-ID": "req-no-fallback"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )
        assert proxy_response.status_code == 500
        assert proxy_response.json()["error"]["message"] == "primary failed"

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        records = usage_response.json()
        assert len(records) == 1
        assert records[0]["provider_id"] == provider_id
        assert records[0]["request_id"] == "req-no-fallback"
        assert records[0]["http_status"] == 500


@pytest.mark.asyncio
async def test_output_guardrail_blocks_non_streaming_response_and_records_spend(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-output-guardrail",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "contains blocked output"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
        )
        policy_response = await client.post(
            "/api/v1/guardrails/policies",
            headers=admin_headers,
            json={
                "name": "Block output",
                "rules": [
                    {
                        "rule_type": "prompt_contains",
                        "effect": "deny",
                        "phase": "response",
                        "values": ["blocked output"],
                    }
                ],
            },
        )
        assert policy_response.status_code == 201
        assignment_response = await client.post(
            "/api/v1/guardrails/assignments",
            headers=admin_headers,
            json={"policy_id": policy_response.json()["id"], "scope_type": "org"},
        )
        assert assignment_response.status_code == 201

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )
        assert proxy_response.status_code == 403
        assert proxy_response.json()["detail"] == (
            "response blocked by guardrail prompt_contains rule"
        )

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        records = usage_response.json()
        assert len(records) == 1
        assert records[0]["http_status"] == 403
        assert records[0]["total_tokens"] == 12
        assert records[0]["error_code"] == "guardrail_output_denied"

        events_response = await client.get(
            "/api/v1/guardrails/events",
            params={"phase": "response", "decision": "blocked"},
            headers=admin_headers,
        )
        assert events_response.status_code == 200
        events = events_response.json()
        assert len(events) == 1
        assert events[0]["phase"] == "response"
        assert events[0]["metadata"]["matched_values"] == ["blocked output"]


@pytest.mark.asyncio
async def test_streaming_is_disabled_when_output_guardrail_is_enforced(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    upstream_called = False

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_called
        upstream_called = True
        return httpx.Response(200, json={})

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
        )
        policy_response = await client.post(
            "/api/v1/guardrails/policies",
            headers=admin_headers,
            json={
                "name": "Guard output",
                "rules": [
                    {
                        "rule_type": "prompt_contains",
                        "effect": "deny",
                        "phase": "response",
                        "values": ["anything"],
                    }
                ],
            },
        )
        assert policy_response.status_code == 201
        assignment_response = await client.post(
            "/api/v1/guardrails/assignments",
            headers=admin_headers,
            json={"policy_id": policy_response.json()["id"], "scope_type": "org"},
        )
        assert assignment_response.status_code == 201

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "stream": True,
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )

    assert proxy_response.status_code == 400
    assert proxy_response.json()["detail"] == (
        "streaming is disabled when enforced output guardrails apply"
    )
    assert upstream_called is False


@pytest.mark.asyncio
async def test_openai_compatible_gateway_contract(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        body = json_loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-contract",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "contract-ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
            model="gpt-contract",
        )
        auth_headers = {"Authorization": f"Bearer {virtual_key}"}

        models_response = await client.get("/v1/models", headers=auth_headers)
        assert models_response.status_code == 200
        assert [model["id"] for model in models_response.json()["data"]] == ["gpt-contract"]

        responses_response = await client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-contract", "input": "hello", "max_output_tokens": 8},
        )
        assert responses_response.status_code == 200
        assert responses_response.json()["output_text"] == "contract-ok"

        completions_response = await client.post(
            "/v1/completions",
            headers=auth_headers,
            json={"model": "gpt-contract", "prompt": "hello", "max_tokens": 8},
        )
        assert completions_response.status_code == 200
        assert completions_response.json()["choices"][0]["text"] == "contract-ok"

        embeddings_response = await client.post(
            "/v1/embeddings",
            headers=auth_headers,
            json={"model": "text-embedding-3-small", "input": "hello"},
        )
        assert embeddings_response.status_code == 501


def json_loads(content: bytes) -> dict:
    import json

    return json.loads(content.decode("utf-8"))


@pytest.mark.asyncio
@pytest.mark.skipif(
    not settings.run_live_openai_tests
    or not settings.openai_api_key
    or not settings.live_openai_model,
    reason=(
        "set BAB_RUN_LIVE_OPENAI_TESTS=true, OPENAI_API_KEY, and BAB_LIVE_OPENAI_MODEL "
        "to run live provider smoke"
    ),
)
async def test_gateway_path_can_call_live_openai(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        assert settings.openai_api_key is not None
        assert settings.live_openai_model is not None
        live_model = settings.live_openai_model
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
            upstream_api_key=settings.openai_api_key,
            model=live_model,
        )
        try:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {virtual_key}"},
                json={
                    "model": live_model,
                    "messages": [{"role": "user", "content": "Reply with only: ok"}],
                    "max_completion_tokens": 8,
                },
            )
        except httpx.ConnectError as exc:
            pytest.skip(f"live OpenAI smoke could not reach upstream: {exc}")
        if response.status_code == 502:
            pytest.skip(f"live OpenAI smoke returned upstream error: {response.text}")
        assert response.status_code == 200
