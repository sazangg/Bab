from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.routes.proxy import get_proxy_http_client
from app.core.bootstrap import sync_default_workspace
from app.core.config import settings
from app.core.migrations import run_database_migrations


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
) -> tuple[str, str]:
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

    allocation_response = await client.post(
        "/api/v1/projects/allocations",
        headers=headers,
        json={
            "name": "Integration allocation",
            "project_id": project_id,
            "offerings": [{"pool_id": pool_id, "model_offering_id": offering_id}],
            "budget_cents": 1000,
            "max_requests": 10,
            "window": "monthly",
        },
    )
    assert allocation_response.status_code == 201

    key_response = await client.post(
        f"/api/v1/projects/{project_id}/keys",
        headers=headers,
        json={"name": "Integration key", "allowed_models": [model]},
    )
    assert key_response.status_code == 201
    virtual_key = key_response.json()["key"]
    assert virtual_key is not None
    return virtual_key, credential_id


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
        virtual_key, credential_id = await _provision_gateway_path(client, admin_headers)

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )
        assert proxy_response.status_code == 200
        assert proxy_response.json()["id"] == "chatcmpl-integration"

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        records = usage_response.json()
        assert len(records) == 1
        assert records[0]["requested_model"] == "gpt-test"
        assert records[0]["provider_model"] == "gpt-test"
        assert records[0]["provider_credential_id"] == credential_id
        assert records[0]["provider_credential_name"] == "Integration OpenAI key"
        assert records[0]["http_status"] == 200
        assert records[0]["total_tokens"] == 17


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
        virtual_key, _credential_id = await _provision_gateway_path(
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
        assert response.status_code == 200
