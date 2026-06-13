import json
from collections.abc import AsyncGenerator
from uuid import UUID

import httpx
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
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
    offering_payload: dict | None = None,
    provider_slug: str = "openai",
) -> tuple[str, str, str]:
    providers = (await client.get("/api/v1/providers", headers=headers)).json()
    provider = next(provider for provider in providers if provider["slug"] == provider_slug)
    provider_id = provider["id"]

    credential_response = await client.post(
        f"/api/v1/providers/{provider_id}/credentials",
        headers=headers,
        json={"name": "Integration provider key", "api_key": upstream_api_key},
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
            **(offering_payload or {}),
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
            "rules": [
                {
                    "name": "Budget",
                    "limit_type": "budget_cents",
                    "limit_value": 1000,
                    "interval_unit": "month",
                },
                {
                    "name": "Requests",
                    "limit_type": "requests",
                    "limit_value": 10,
                    "interval_unit": "month",
                },
            ],
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
async def test_provider_runtime_config_validation_accepts_typed_policy(app_client, db_session):
    await sync_default_workspace(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        response = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Typed runtime provider",
                "slug": "typed-runtime-provider",
                "base_url": "https://typed.example/v1",
                "capabilities": {"chat": True, "streaming": False},
                "request_timeout_seconds": 45,
                "max_body_bytes": 1048576,
                "max_concurrent_requests": 5,
                "retry_policy": {
                    "enabled": True,
                    "max_attempts": 2,
                    "backoff": "constant",
                    "initial_delay_ms": 0,
                    "max_delay_ms": 100,
                    "retry_on_status": [500, 503],
                },
                "circuit_breaker_policy": {
                    "enabled": True,
                    "failure_threshold_pct": 50,
                    "min_request_count": 2,
                    "window_seconds": 60,
                    "cooldown_seconds": 30,
                },
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["retry_policy"]["max_attempts"] == 2
    assert "fallback_policy" not in body


@pytest.mark.asyncio
async def test_provider_runtime_config_validation_rejects_unknown_and_invalid_fields(
    app_client,
    db_session,
):
    await sync_default_workspace(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        response = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Invalid runtime provider",
                "base_url": "https://invalid.example/v1",
                "capabilities": {"chat": "yes"},
                "fallback_policy": {"enabled": True},
                "retry_policy": {"enabled": "true", "max_attempts": 0},
            },
        )

    assert response.status_code == 422
    details = response.json()["errors"]
    locations = {tuple(item["loc"]) for item in details}
    assert ("body", "capabilities", "chat") in locations
    assert ("body", "fallback_policy") in locations
    assert ("body", "retry_policy", "enabled") in locations
    assert ("body", "retry_policy", "max_attempts") in locations


@pytest.mark.asyncio
async def test_provider_credential_response_exposes_secret_metadata_not_secret(
    app_client,
    db_session,
):
    await sync_default_workspace(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        provider_response = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Secret metadata provider",
                "slug": "secret-metadata-provider",
                "base_url": "https://secret.example/v1",
            },
        )
        assert provider_response.status_code == 201
        provider_id = provider_response.json()["id"]
        credential_response = await client.post(
            f"/api/v1/providers/{provider_id}/credentials",
            headers=admin_headers,
            json={"name": "Secret metadata credential", "api_key": "sk-secret-metadata"},
        )

    assert credential_response.status_code == 201
    body = credential_response.json()
    assert body["secret_backend"] == "local"
    assert body["secret_reference"] == f"provider_credentials/{body['id']}/api_key"
    assert body["key_prefix"] == "sk-s..."
    assert "api_key" not in body
    assert "api_key_encrypted" not in body
    assert "sk-secret-metadata" not in str(body)


@pytest.mark.asyncio
async def test_migrations_create_current_schema(tmp_path) -> None:
    database_path = tmp_path / "migration-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    await run_database_migrations(engine)

    async with engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
        provider_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_columns("providers")
            }
        )
        credential_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"]
                for item in inspect(sync_connection).get_columns("provider_credentials")
            }
        )
        virtual_key_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_columns("virtual_keys")
            }
        )
        virtual_key_indexes = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_indexes("virtual_keys")
            }
        )
        project_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_columns("projects")
            }
        )
        project_indexes = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_indexes("projects")
            }
        )
        project_unique_constraints = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_unique_constraints("projects")
            }
        )
        policy_owner_schema = await connection.run_sync(_policy_owner_schema)

    await engine.dispose()

    assert "alembic_version" in table_names
    assert "provider_credentials" in table_names
    assert "credential_pool_credentials" in table_names
    assert "usage_records" in table_names
    assert "fallback_policy" not in provider_columns
    assert {"secret_backend", "secret_reference"} <= credential_columns
    assert {
        "created_by",
        "last_used_at",
        "revoked_by",
        "revoked_reason",
    } <= virtual_key_columns
    assert {
        "ix_virtual_keys_created_by",
        "ix_virtual_keys_last_used_at",
        "ix_virtual_keys_project_revoked",
    } <= virtual_key_indexes
    assert "slug" in project_columns
    assert "ix_projects_slug" in project_indexes
    assert "uq_projects_org_team_slug" in project_unique_constraints
    for table_schema in policy_owner_schema.values():
        assert {
            "owning_scope_type",
            "owning_team_id",
            "owning_project_id",
            "owning_virtual_key_id",
        } <= table_schema["columns"]
        assert {
            "owning_scope_type",
            "owning_team_id",
            "owning_project_id",
            "owning_virtual_key_id",
        } <= table_schema["indexed_columns"]
        assert {
            ("owning_team_id", "teams", "id"),
            ("owning_project_id", "projects", "id"),
            ("owning_virtual_key_id", "virtual_keys", "id"),
        } <= table_schema["foreign_keys"]


def _policy_owner_schema(sync_connection):
    inspector = inspect(sync_connection)
    schema = {}
    for table_name in ("access_policies", "limit_policies"):
        indexes = inspector.get_indexes(table_name)
        foreign_keys = inspector.get_foreign_keys(table_name)
        schema[table_name] = {
            "columns": {item["name"] for item in inspector.get_columns(table_name)},
            "indexed_columns": {
                column_name for index in indexes for column_name in index.get("column_names", [])
            },
            "foreign_keys": {
                (
                    foreign_key["constrained_columns"][0],
                    foreign_key["referred_table"],
                    foreign_key["referred_columns"][0],
                )
                for foreign_key in foreign_keys
                if len(foreign_key.get("constrained_columns") or []) == 1
                and len(foreign_key.get("referred_columns") or []) == 1
            },
        }
    return schema


@pytest.mark.asyncio
async def test_anthropic_migration_backfill_requires_canonical_base_url(tmp_path) -> None:
    database_path = tmp_path / "migration-backfill.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    def upgrade_to(connection, revision: str) -> None:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    async with engine.begin() as connection:
        await connection.run_sync(upgrade_to, "20260605_0017")
        now = "2026-06-05 00:00:00"
        await connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, name, slug, is_active, created_at) "
                "VALUES ('org1', 'Org', 'org', 1, :now)"
            ),
            {"now": now},
        )
        provider_sql = text(
            "INSERT INTO providers ("
            "id, org_id, name, slug, base_url, api_key_encrypted, adapter_type, "
            "display_name, description, capabilities, supported_integration, "
            "request_timeout_seconds, max_body_bytes, retry_policy, model_sync_mode, "
            "circuit_breaker_policy, max_concurrent_requests, is_favorite, is_active, "
            "created_at, updated_at) VALUES ("
            ":id, 'org1', :name, :slug, :base_url, NULL, 'openai_compat', "
            "NULL, NULL, '{}', 'openai_compatible_default', NULL, NULL, NULL, NULL, "
            "'{}', NULL, 0, 1, :now, :now)"
        )
        rows = [
            {
                "id": "catalog",
                "name": "Anthropic",
                "slug": "anthropic",
                "base_url": "https://api.anthropic.com/v1/",
                "now": now,
            },
            {
                "id": "custom-slug",
                "name": "Custom",
                "slug": "anthropic-custom",
                "base_url": "https://custom.example/v1",
                "now": now,
            },
            {
                "id": "custom-name",
                "name": "Anthropic Compatible",
                "slug": "anthropic-like",
                "base_url": "https://another.example/v1",
                "now": now,
            },
        ]
        for row in rows:
            await connection.execute(provider_sql, row)
        await connection.run_sync(upgrade_to, "head")
        integrations = dict(
            (
                await connection.execute(text("SELECT id, supported_integration FROM providers"))
            ).all()
        )

    await engine.dispose()
    assert integrations == {
        "catalog": "anthropic_messages",
        "custom-slug": "openai_compatible_default",
        "custom-name": "openai_compatible_default",
    }


@pytest.mark.asyncio
async def test_provider_slugs_are_unique_within_an_organization(app_client, db_session) -> None:
    await sync_default_workspace(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        first = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={"name": "First", "slug": " Same Slug ", "base_url": "https://one.example/v1"},
        )
        duplicate = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={"name": "Second", "slug": "same-slug", "base_url": "https://two.example/v1"},
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "provider slug already exists"


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
        assert records[0]["provider_credential_name"] == "Integration provider key"
        assert records[0]["request_id"] == proxy_response.headers["x-request-id"]
        assert records[0]["http_status"] == 200
        assert records[0]["prompt_tokens"] == 12
        assert records[0]["completion_tokens"] == 5
        assert records[0]["total_tokens"] == 17
        assert records[0]["usage_source"] == "provider_reported"

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
async def test_native_anthropic_messages_preserves_shape_and_records_usage(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert json.loads(request.content) == {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Say hello."}],
            "max_tokens": 32,
            "system": "Be concise.",
        }
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello."}],
                "model": "claude-test",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client
    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        virtual_key, credential_id, _ = await _provision_gateway_path(
            client,
            admin_headers,
            upstream_api_key="sk-ant-test",
            model="claude-test",
            provider_slug="anthropic",
        )
        response = await client.post(
            "/v1/messages",
            headers={"x-api-key": virtual_key},
            json={
                "model": "claude-test",
                "messages": [{"role": "user", "content": "Say hello."}],
                "max_tokens": 32,
                "system": "Be concise.",
            },
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    records = usage_response.json()
    assert len(records) == 1
    assert records[0]["provider_credential_id"] == credential_id
    assert records[0]["prompt_tokens"] == 8
    assert records[0]["completion_tokens"] == 3
    assert records[0]["total_tokens"] == 11
    assert records[0]["usage_source"] == "provider_reported"


@pytest.mark.asyncio
async def test_native_anthropic_messages_applies_output_guardrails(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        return httpx.Response(
            200,
            json={
                "id": "msg_output_guardrail",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "contains blocked output"}],
                "model": "claude-test",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client
    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _credential_id, _provider_id = await _provision_gateway_path(
            client,
            admin_headers,
            upstream_api_key="sk-ant-output",
            model="claude-test",
            provider_slug="anthropic",
        )
        policy_response = await client.post(
            "/api/v1/guardrails/policies",
            headers=admin_headers,
            json={
                "name": "Block Anthropic output",
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

        response = await client.post(
            "/v1/messages",
            headers={"x-api-key": virtual_key},
            json={
                "model": "claude-test",
                "messages": [{"role": "user", "content": "Say hello."}],
                "max_tokens": 32,
            },
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        events_response = await client.get(
            "/api/v1/guardrails/events",
            params={"phase": "response", "decision": "blocked"},
            headers=admin_headers,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "response blocked by guardrail prompt_contains rule"
    records = usage_response.json()
    assert len(records) == 1
    assert records[0]["http_status"] == 403
    assert records[0]["error_code"] == "guardrail_output_denied"
    assert records[0]["total_tokens"] == 11
    events = events_response.json()
    assert len(events) == 1
    assert events[0]["metadata"]["matched_values"] == ["blocked output"]


@pytest.mark.asyncio
async def test_native_anthropic_messages_rejects_missing_and_conflicting_virtual_keys(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        missing = await client.post(
            "/v1/messages",
            json={"model": "claude-test", "messages": [{"role": "user", "content": "Hi"}]},
        )
        conflicting = await client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer bab-one", "x-api-key": "bab-two"},
            json={"model": "claude-test", "messages": [{"role": "user", "content": "Hi"}]},
        )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "missing virtual key"
    assert conflicting.status_code == 400
    assert conflicting.json()["detail"] == "conflicting virtual key headers"


@pytest.mark.asyncio
async def test_native_anthropic_messages_records_upstream_failure(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"type": "error", "error": {"type": "authentication_error"}}
        )

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client
    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _, _ = await _provision_gateway_path(
            client,
            admin_headers,
            model="claude-failure",
            provider_slug="anthropic",
        )
        response = await client.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "claude-failure",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 16,
            },
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 401
    assert response.json()["type"] == "error"
    records = usage_response.json()
    assert len(records) == 1
    assert records[0]["http_status"] == 401
    assert records[0]["error_code"] == "provider_upstream_error"
    assert records[0]["usage_source"] == "unknown"
    assert records[0]["total_tokens"] is None


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
        credential_response = await client.post(
            f"/api/v1/providers/{provider_id}/credentials",
            headers=admin_headers,
            json={"name": "Access-only credential", "api_key": "access-only-secret"},
        )
        assert credential_response.status_code == 201
        pool_credential_response = await client.post(
            f"/api/v1/providers/{provider_id}/pools/{pool_id}/credentials",
            headers=admin_headers,
            json={"provider_credential_id": credential_response.json()["id"]},
        )
        assert pool_credential_response.status_code == 201

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
            limit_payload={
                "rules": [
                    {
                        "name": "Two requests",
                        "limit_type": "requests",
                        "limit_value": 2,
                        "interval_unit": "day",
                    }
                ]
            },
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
        assert limited_response.status_code == 429
        assert limited_response.json()["detail"] == "limit policy request limit exceeded"

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        limit_record = usage_response.json()[0]
        assert limit_record["http_status"] == 429
        assert limit_record["error_code"] == "limit_policy_denied"


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
        assert update_provider.status_code == 422

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
async def test_input_guardrail_denial_does_not_consume_request_limit(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-after-guardrail",
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
            limit_payload={
                "rules": [
                    {
                        "name": "One accepted request",
                        "limit_type": "requests",
                        "limit_value": 1,
                        "interval_unit": "day",
                    }
                ]
            },
        )
        policy_response = await client.post(
            "/api/v1/guardrails/policies",
            headers=admin_headers,
            json={
                "name": "Block prompt",
                "rules": [
                    {
                        "rule_type": "prompt_contains",
                        "effect": "deny",
                        "phase": "request",
                        "values": ["blocked prompt"],
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

        blocked_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "blocked prompt"}],
            },
        )
        assert blocked_response.status_code == 403

        accepted_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "allowed prompt"}],
            },
        )
        assert accepted_response.status_code == 200

        limited_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "allowed prompt"}],
            },
        )
        assert limited_response.status_code == 429


@pytest.mark.asyncio
async def test_streaming_is_allowed_when_output_guardrail_is_monitor_only(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    upstream_called = False

    async def upstream_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal upstream_called
        upstream_called = True
        return httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"content":"contains "}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"blocked output"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
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
                "name": "Monitor output",
                "enforcement_mode": "monitor",
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
                "stream": True,
                "messages": [{"role": "user", "content": "Say hello."}],
            },
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        events_response = await client.get(
            "/api/v1/guardrails/events",
            params={"phase": "response", "decision": "dry_run"},
            headers=admin_headers,
        )

    assert proxy_response.status_code == 200
    assert upstream_called is True
    records = usage_response.json()
    assert len(records) == 1
    assert records[0]["usage_source"] == "estimated"
    assert records[0]["total_tokens"] > 0
    events = events_response.json()
    assert len(events) == 1
    assert events[0]["metadata"]["matched_values"] == ["blocked output"]


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
