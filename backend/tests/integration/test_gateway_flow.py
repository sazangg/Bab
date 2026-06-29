import json
from collections.abc import AsyncGenerator
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.routes.proxy import get_proxy_http_client
from app.core.bootstrap import sync_default_workspace
from app.core.config import settings
from app.core.database import Base
from app.core.migrations import get_migration_state, run_database_migrations
from app.modules.gateway_history.internal.models import (
    GatewayPolicyDecision,
    GatewayRequest,
    GatewayRouteAttempt,
)
from app.modules.guardrails.internal.models import GuardrailEvent
from app.modules.keys import facade as keys_facade
from app.modules.keys.schemas import ResolveAccessRequest
from app.modules.usage.internal.models import LimitPolicyReservation, UsageRecord


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
            "public_models": [
                {
                    "public_model_name": model,
                    "routing_mode": "single_route",
                    "candidates": [
                        {
                            "provider_id": provider_id,
                            "credential_pool_id": pool_id,
                            "model_offering_id": offering_id,
                        }
                    ],
                }
            ],
        },
    )
    assert access_response.status_code == 201
    access_shared_policy_id = access_response.json()["policy_id"]

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
    limit_shared_policy_id = limit_response.json()["policy_id"]

    for payload in (
        {
            "policy_type": "access",
            "policy_id": access_shared_policy_id,
            "scope_type": "project",
            "project_id": project_id,
        },
        {
            "policy_type": "limit",
            "policy_id": limit_shared_policy_id,
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
        public_model_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"]
                for item in inspect(sync_connection).get_columns("access_policy_public_models")
            }
        )
        route_candidate_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"]
                for item in inspect(sync_connection).get_columns("access_policy_route_candidates")
            }
        )
        gateway_request_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_columns("gateway_requests")
            }
        )
        usage_record_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"] for item in inspect(sync_connection).get_columns("usage_records")
            }
        )
        committed_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"]: item
                for item in inspect(sync_connection).get_columns(
                    "limit_policy_committed_usage"
                )
            }
        )
        reservation_columns = await connection.run_sync(
            lambda sync_connection: {
                item["name"]: item
                for item in inspect(sync_connection).get_columns("limit_policy_reservations")
            }
        )
        performance_indexes = await connection.run_sync(_performance_indexes)
        policy_owner_schema = await connection.run_sync(_policy_owner_schema)
    migration_state = await get_migration_state(engine)

    await engine.dispose()

    assert set(table_names) == {*Base.metadata.tables, "alembic_version"}
    assert migration_state["is_current"] is True
    assert migration_state["current_revision"] == "20260629_0001"
    assert migration_state["head_revision"] == "20260629_0001"
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
    } <= virtual_key_indexes
    assert "slug" in project_columns
    assert "ix_projects_slug" in project_indexes
    assert "uq_projects_org_team_slug" in project_unique_constraints
    assert {
        "public_model_name",
        "routing_mode",
        "fallback_on",
        "max_route_attempts",
    } <= public_model_columns
    assert {
        "public_model_id",
        "provider_id",
        "credential_pool_id",
        "model_offering_id",
        "priority",
    } <= route_candidate_columns
    assert {
        "gateway_endpoint",
        "requested_model",
        "attempt_count",
        "fallback_attempted",
        "final_candidate_id",
    } <= gateway_request_columns
    assert {
        "gateway_request_id",
        "public_model_id",
        "route_candidate_id",
        "routing_attempt_index",
        "is_final_attempt",
        "attempt_failure_reason",
    } <= usage_record_columns
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
    required_columns = {
        "limit_policy_id",
        "limit_policy_revision_id",
        "limit_policy_rule_id",
        "limit_policy_assignment_id",
    }
    assert all(not committed_columns[name]["nullable"] for name in required_columns)
    assert all(not reservation_columns[name]["nullable"] for name in required_columns)
    assert {
        "ix_usage_records_org_created_at_id",
        "ix_gateway_requests_org_started_id",
        "ix_policy_assignments_org_type_active_created",
        "ix_gateway_route_attempts_org_request_attempt",
        "ix_gateway_policy_decisions_org_request_created",
    } <= performance_indexes


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


def _performance_indexes(sync_connection) -> set[str]:
    inspector = inspect(sync_connection)
    return {
        index["name"]
        for table_name in (
            "usage_records",
            "gateway_requests",
            "policy_assignments",
            "gateway_route_attempts",
            "gateway_policy_decisions",
        )
        for index in inspector.get_indexes(table_name)
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
        records = usage_response.json()["items"]
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
    records = usage_response.json()["items"]
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
    records = usage_response.json()["items"]
    assert len(records) == 1
    assert records[0]["http_status"] == 403
    assert records[0]["error_code"] == "guardrail_output_denied"
    assert records[0]["total_tokens"] == 11
    events = events_response.json()["items"]
    assert len(events) == 1
    assert events[0]["metadata"]["matched_values"] == ["blocked output"]
    assert records[0]["route_attempt_id"] is not None
    assert events[0]["route_attempt_id"] == records[0]["route_attempt_id"]
    route_attempt = await db_session.get(
        GatewayRouteAttempt,
        UUID(records[0]["route_attempt_id"]),
    )
    assert route_attempt is not None
    assert route_attempt.status == "blocked"
    assert route_attempt.error_code == "guardrail_output_denied"


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
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:bab:error:provider-upstream",
        "title": "Upstream Provider Error",
        "status": 401,
        "detail": "Upstream provider request failed",
        "instance": "/v1/messages",
        "failure_reason": "provider_error",
        "upstream_status": 401,
    }
    records = usage_response.json()["items"]
    assert len(records) == 1
    assert records[0]["http_status"] == 401
    assert records[0]["error_code"] == "provider_upstream_error"
    assert records[0]["usage_source"] == "unknown"
    assert records[0]["total_tokens"] is None


@pytest.mark.asyncio
async def test_malformed_successful_upstream_response_records_bad_gateway(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["invalid"])

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _, _ = await _provision_gateway_path(client, admin_headers)
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "Hello"}]},
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["failure_reason"] == "invalid_response"
    records = usage_response.json()["items"]
    assert records[0]["http_status"] == 502
    assert records[0]["error_code"] == "provider_upstream_error"
    gateway_request = (await db_session.execute(select(GatewayRequest))).scalar_one()
    assert gateway_request.final_http_status == 502
    assert gateway_request.final_error_code == "provider_upstream_error"
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_native_anthropic_messages_falls_back_to_second_candidate(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["model"])
        if body["model"] == "claude-primary":
            return httpx.Response(503, json={"type": "error", "error": {"type": "overloaded"}})
        return httpx.Response(
            200,
            json={
                "id": "msg_fallback",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "anthropic-fallback-ok"}],
                "model": "claude-secondary",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 4},
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
        providers = (await client.get("/api/v1/providers", headers=admin_headers)).json()
        provider_id = next(
            provider["id"] for provider in providers if provider["slug"] == "anthropic"
        )
        primary_pool_id, primary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=provider_id,
            model="claude-primary",
        )
        secondary_pool_id, secondary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=provider_id,
            model="claude-secondary",
        )
        team = await client.post(
            "/api/v1/teams",
            headers=admin_headers,
            json={"name": "Anthropic Fallback Team", "slug": "anthropic-fallback-team"},
        )
        project = await client.post(
            f"/api/v1/teams/{team.json()['id']}/projects",
            headers=admin_headers,
            json={"name": "Anthropic Fallback Project"},
        )
        access = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Anthropic fallback access",
                "public_models": [
                    {
                        "public_model_name": "claude-large",
                        "routing_mode": "ordered_fallback",
                        "fallback_on": ["provider_5xx"],
                        "candidates": [
                            {
                                "provider_id": provider_id,
                                "credential_pool_id": primary_pool_id,
                                "model_offering_id": primary_model_id,
                                "priority": 10,
                            },
                            {
                                "provider_id": provider_id,
                                "credential_pool_id": secondary_pool_id,
                                "model_offering_id": secondary_model_id,
                                "priority": 20,
                            },
                        ],
                    }
                ],
            },
        )
        limits = await client.post(
            "/api/v1/policies/limits",
            headers=admin_headers,
            json={"name": "Anthropic fallback limits", "rules": []},
        )
        assert access.status_code == 201
        assert limits.status_code == 201
        for payload in (
            {
                "policy_type": "access",
                "policy_id": access.json()["policy_id"],
                "scope_type": "project",
                "project_id": project.json()["id"],
            },
            {
                "policy_type": "limit",
                "policy_id": limits.json()["policy_id"],
                "scope_type": "project",
                "project_id": project.json()["id"],
            },
        ):
            assignment = await client.post(
                "/api/v1/policies/assignments",
                headers=admin_headers,
                json=payload,
            )
            assert assignment.status_code == 201
        key = await client.post(
            f"/api/v1/projects/{project.json()['id']}/keys",
            headers=admin_headers,
            json={"name": "Anthropic fallback key"},
        )
        response = await client.post(
            "/v1/messages",
            headers={"x-api-key": key.json()["key"]},
            json={
                "model": "claude-large",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 16,
            },
        )
        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "anthropic-fallback-ok"
    assert calls == ["claude-primary", "claude-secondary"]
    records = usage_response.json()["items"]
    assert [record["provider_model"] for record in records[:2]] == [
        "claude-secondary",
        "claude-primary",
    ]
    assert records[0]["error_code"] is None
    assert records[0]["is_final_attempt"] is True
    assert records[1]["attempt_failure_reason"] == "provider_5xx"
    assert records[1]["is_final_attempt"] is False
    app_client.dependency_overrides.clear()


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
            json={"provider_model_name": "gpt-access-only"},
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
                "public_models": [
                    {
                        "public_model_name": "gpt-access-only",
                        "routing_mode": "single_route",
                        "candidates": [
                            {
                                "provider_id": provider_id,
                                "credential_pool_id": pool_id,
                                "model_offering_id": offering_id,
                            }
                        ],
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
                "policy_id": access_response.json()["policy_id"],
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
        limit_record = usage_response.json()["items"][0]
        assert limit_record["http_status"] == 429
        assert limit_record["error_code"] == "limit_policy_denied"
        assert limit_record["gateway_endpoint"] == "chat_completions"
        assert limit_record["gateway_request_id"] is not None
        assert limit_record["route_attempt_id"] is not None

        decisions = (
            await db_session.scalars(
                select(GatewayPolicyDecision)
                .where(GatewayPolicyDecision.decision_type == "limit")
                .order_by(GatewayPolicyDecision.created_at)
            )
        ).all()
        assert [decision.outcome for decision in decisions] == [
            "reserved",
            "reserved",
            "denied",
        ]
        assert decisions[-1].reason_code == "request_limit"
        assert decisions[-1].effective_action == "deny"
        assert decisions[-1].assignment_id is not None
        assert decisions[-1].rule_id is not None
        assert str(decisions[-1].route_attempt_id) == limit_record["route_attempt_id"]
        assert decisions[-1].dimension_snapshot["limit_type"] == "requests"
        assert decisions[-1].metadata_["current_usage"] == 2
        route_attempt = await db_session.get(
            GatewayRouteAttempt,
            UUID(limit_record["route_attempt_id"]),
        )
        assert route_attempt is not None
        assert route_attempt.status == "blocked"
        assert route_attempt.error_code == "limit_exceeded"


@pytest.mark.asyncio
async def test_provider_body_size_failure_closes_route_attempt(app_client, db_session) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called after body-size rejection")

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
        update_response = await client.patch(
            f"/api/v1/providers/{provider_id}",
            headers=admin_headers,
            json={"max_body_bytes": 20},
        )
        assert update_response.status_code == 200

        proxy_response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "body exceeds provider max"}],
            },
        )

    assert proxy_response.status_code == 413
    assert proxy_response.json()["detail"] == "request body exceeds provider limit"
    route_attempt = await db_session.scalar(select(GatewayRouteAttempt))
    assert route_attempt is not None
    assert route_attempt.status == "blocked"
    assert route_attempt.error_code == "request_body_too_large"


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
        assert proxy_response.json()["type"] == "urn:bab:error:provider-upstream"
        assert proxy_response.json()["failure_reason"] == "provider_5xx"

        usage_response = await client.get("/api/v1/usage/records", headers=admin_headers)
        assert usage_response.status_code == 200
        records = usage_response.json()["items"]
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
        records = usage_response.json()["items"]
        assert len(records) == 1
        assert records[0]["http_status"] == 403
        assert records[0]["total_tokens"] == 12
        assert records[0]["error_code"] == "guardrail_output_denied"

        events_response = await client.get(
            "/api/v1/guardrails/events",
            params={"phase": "response", "decision": "blocked"},
            headers=admin_headers,
        )
        first_events_page_response = await client.get(
            "/api/v1/guardrails/events",
            params={"limit": 1},
            headers=admin_headers,
        )
        first_events_page = first_events_page_response.json()
        second_events_page_response = await client.get(
            "/api/v1/guardrails/events",
            params={
                "limit": 1,
                "before_at": first_events_page["next_before_at"],
                "before_id": first_events_page["next_before_id"],
            },
            headers=admin_headers,
        )
        invalid_events_limit_response = await client.get(
            "/api/v1/guardrails/events",
            params={"limit": 0},
            headers=admin_headers,
        )
        assert events_response.status_code == 200
        events = events_response.json()["items"]
        assert len(events) == 1
        assert events[0]["phase"] == "response"
        assert events[0]["gateway_request_id"] == records[0]["gateway_request_id"]
        assert events[0]["metadata"]["matched_values"] == ["blocked output"]
        assert first_events_page_response.status_code == 200
        [latest_event] = first_events_page["items"]
        assert first_events_page["limit"] == 1
        assert first_events_page["has_more"] is True
        assert first_events_page["next_before_at"] == latest_event["created_at"]
        assert first_events_page["next_before_id"] == latest_event["id"]
        assert second_events_page_response.status_code == 200
        second_events_page = second_events_page_response.json()
        assert len(second_events_page["items"]) == 1
        assert second_events_page["items"][0]["id"] != latest_event["id"]
        assert second_events_page["has_more"] is False
        assert second_events_page["next_before_at"] is None
        assert second_events_page["next_before_id"] is None
        assert invalid_events_limit_response.status_code == 422
        assert invalid_events_limit_response.headers["content-type"].startswith(
            "application/problem+json"
        )
        stored_event = await db_session.scalar(
            select(GuardrailEvent).where(GuardrailEvent.id == UUID(events[0]["id"]))
        )
        assert stored_event.gateway_request_id == UUID(records[0]["gateway_request_id"])
        decisions = (
            await db_session.scalars(
                select(GatewayPolicyDecision)
                .where(GatewayPolicyDecision.decision_type == "guardrail")
                .order_by(GatewayPolicyDecision.created_at)
            )
        ).all()
        assert [decision.stage for decision in decisions] == [
            "request_guardrail",
            "response_guardrail",
        ]
        assert [decision.outcome for decision in decisions] == ["allowed", "denied"]
        assert decisions[-1].rule_id == UUID(events[0]["rule_id"])
        assert decisions[-1].policy_revision_id == stored_event.policy_revision_id
        assert decisions[-1].assignment_id is not None
        assert decisions[-1].assignment_mode == "enforce"
        assert decisions[-1].assignment_scope_type == "org"


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
    gateway_request = await db_session.scalar(select(GatewayRequest))
    assert gateway_request is not None
    assert gateway_request.final_http_status == 400
    assert gateway_request.final_error_code == "streaming_response_guardrail_unsupported"
    route_attempt = await db_session.scalar(select(GatewayRouteAttempt))
    assert route_attempt is not None
    assert route_attempt.status == "blocked"
    assert route_attempt.error_code == "streaming_response_guardrail_unsupported"
    active_reservations = (
        await db_session.scalars(
            select(LimitPolicyReservation).where(LimitPolicyReservation.status == "active")
        )
    ).all()
    assert active_reservations == []


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
        events_response = await client.get(
            "/api/v1/guardrails/events",
            headers=admin_headers,
        )
        events = events_response.json()["items"]
        blocked_event = next(event for event in events if event["decision"] == "blocked")
        assert blocked_event["gateway_request_id"] is not None
        assert blocked_event["route_attempt_id"] is not None
        blocked_usage_record = await db_session.scalar(
            select(UsageRecord).where(
                UsageRecord.gateway_request_id == UUID(blocked_event["gateway_request_id"])
            )
        )
        assert blocked_usage_record is not None
        assert blocked_usage_record.route_attempt_id == UUID(blocked_event["route_attempt_id"])
        route_attempt = await db_session.get(
            GatewayRouteAttempt,
            UUID(blocked_event["route_attempt_id"]),
        )
        assert route_attempt is not None
        assert route_attempt.status == "blocked"
        assert route_attempt.error_code == "guardrail_denied"
        decisions = (
            await db_session.scalars(
                select(GatewayPolicyDecision)
                .where(GatewayPolicyDecision.decision_type == "guardrail")
                .order_by(GatewayPolicyDecision.created_at)
            )
        ).all()
        assert "denied" in [decision.outcome for decision in decisions]
        assert any(
            decision.stage == "request_guardrail" and decision.outcome == "allowed"
            for decision in decisions
        )


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
            params={"phase": "response", "decision": "would_block"},
            headers=admin_headers,
        )

    assert proxy_response.status_code == 200
    assert upstream_called is True
    records = usage_response.json()["items"]
    assert len(records) == 1
    assert records[0]["usage_source"] == "estimated"
    assert records[0]["total_tokens"] > 0
    events = events_response.json()["items"]
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


@pytest.mark.asyncio
async def test_chat_completion_falls_back_to_second_public_model_candidate(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "primary.example.test" in str(request.url):
            return httpx.Response(503, json={"error": "primary down"})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_fallback",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "fallback-ok"},
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
        primary_provider = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={"name": "Primary fallback", "base_url": "https://primary.example.test/v1"},
        )
        secondary_provider = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={"name": "Secondary fallback", "base_url": "https://secondary.example.test/v1"},
        )
        assert primary_provider.status_code == 201
        assert secondary_provider.status_code == 201
        primary_pool_id, primary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=primary_provider.json()["id"],
            model="primary-chat",
        )
        secondary_pool_id, secondary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=secondary_provider.json()["id"],
            model="secondary-chat",
        )
        team = await client.post(
            "/api/v1/teams",
            headers=admin_headers,
            json={"name": "Fallback Team", "slug": "fallback-team"},
        )
        project = await client.post(
            f"/api/v1/teams/{team.json()['id']}/projects",
            headers=admin_headers,
            json={"name": "Fallback Project"},
        )
        assert team.status_code == 201
        assert project.status_code == 201
        access = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Fallback access",
                "public_models": [
                    {
                        "public_model_name": "chat-large",
                        "routing_mode": "ordered_fallback",
                        "fallback_on": ["provider_5xx"],
                        "candidates": [
                            {
                                "provider_id": primary_provider.json()["id"],
                                "credential_pool_id": primary_pool_id,
                                "model_offering_id": primary_model_id,
                                "priority": 10,
                            },
                            {
                                "provider_id": secondary_provider.json()["id"],
                                "credential_pool_id": secondary_pool_id,
                                "model_offering_id": secondary_model_id,
                                "priority": 20,
                            },
                        ],
                    }
                ],
            },
        )
        limits = await client.post(
            "/api/v1/policies/limits",
            headers=admin_headers,
            json={"name": "Fallback limits", "rules": []},
        )
        assert access.status_code == 201
        assert limits.status_code == 201
        for payload in (
            {
                "policy_type": "access",
                "policy_id": access.json()["policy_id"],
                "scope_type": "project",
                "project_id": project.json()["id"],
            },
            {
                "policy_type": "limit",
                "policy_id": limits.json()["policy_id"],
                "scope_type": "project",
                "project_id": project.json()["id"],
            },
        ):
            assignment = await client.post(
                "/api/v1/policies/assignments",
                headers=admin_headers,
                json=payload,
            )
            assert assignment.status_code == 201
        key = await client.post(
            f"/api/v1/projects/{project.json()['id']}/keys",
            headers=admin_headers,
            json={"name": "Fallback key"},
        )
        assert key.status_code == 201

        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.json()['key']}"},
            json={"model": "chat-large", "messages": [{"role": "user", "content": "hello"}]},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)
        trace_list = await client.get("/api/v1/gateway-history/requests", headers=admin_headers)
        summary = await client.get("/api/v1/usage/summary", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "fallback-ok"
    assert len(calls) == 2
    assert "primary.example.test" in calls[0]
    assert "secondary.example.test" in calls[1]
    records = usage.json()["items"]
    assert [record["provider_model"] for record in records[:2]] == [
        "secondary-chat",
        "primary-chat",
    ]
    assert records[0]["error_code"] is None
    assert records[0]["is_final_attempt"] is True
    assert records[0]["primary_route_candidate_id"] == records[1]["route_candidate_id"]
    assert records[0]["gateway_request_id"] == records[1]["gateway_request_id"]
    assert records[1]["attempt_failure_reason"] == "provider_5xx"
    assert records[1]["is_final_attempt"] is False
    assert trace_list.status_code == 200
    trace_items = trace_list.json()["items"]
    assert len(trace_items) == 1
    assert trace_items[0]["fallback_attempted"] is True
    assert trace_items[0]["final_provider_model"] == "secondary-chat"
    assert trace_items[0]["final_provider_name"] == "Secondary fallback"
    assert set(trace_items[0]["involved_provider_names"]) == {
        "Primary fallback",
        "Secondary fallback",
    }
    totals = summary.json()["totals"]
    assert totals["requests"] == 1
    assert totals["successful_requests"] == 1
    assert totals["failed_requests"] == 0
    db_session.expire_all()
    gateway_requests = (await db_session.execute(select(GatewayRequest))).scalars().all()
    assert len(gateway_requests) == 1
    assert gateway_requests[0].attempt_count == 2
    assert gateway_requests[0].fallback_attempted is True
    assert gateway_requests[0].final_http_status == 200
    assert gateway_requests[0].final_provider_model == "secondary-chat"
    route_attempts = (
        (
            await db_session.execute(
                select(GatewayRouteAttempt).order_by(GatewayRouteAttempt.attempt_index)
            )
        )
        .scalars()
        .all()
    )
    assert [attempt.status for attempt in route_attempts] == ["failed", "succeeded"]
    assert route_attempts[0].failure_reason == "provider_5xx"
    assert gateway_requests[0].final_route_attempt_id == route_attempts[1].id
    usage_records = (
        (
            await db_session.execute(
                select(UsageRecord).order_by(UsageRecord.is_final_attempt.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(usage_records) == 2
    assert usage_records[0].is_final_attempt is False
    assert usage_records[0].route_attempt_id == route_attempts[0].id
    assert usage_records[1].is_final_attempt is True
    assert usage_records[1].route_attempt_id == route_attempts[1].id
    decisions = (
        (
            await db_session.execute(
                select(GatewayPolicyDecision).order_by(GatewayPolicyDecision.created_at)
            )
        )
        .scalars()
        .all()
    )
    access_decisions = [decision for decision in decisions if decision.decision_type == "access"]
    assert len(access_decisions) == 1
    assert access_decisions[0].stage == "access_resolution"
    assert access_decisions[0].outcome == "allowed"
    assert access_decisions[0].policy_id is not None
    assert access_decisions[0].assignment_id is not None
    assert access_decisions[0].assignment_mode == "enforce"
    assert access_decisions[0].assignment_scope_type == "project"
    provider_routing_decisions = [
        decision for decision in decisions if decision.decision_type == "provider_routing"
    ]
    assert [decision.outcome for decision in provider_routing_decisions] == [
        "selected",
        "selected",
    ]
    assert [decision.assignment_id for decision in provider_routing_decisions] == [
        access_decisions[0].assignment_id,
        access_decisions[0].assignment_id,
    ]
    assert all(
        decision.assignment_scope_type == "project" for decision in provider_routing_decisions
    )
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_completion_returns_primary_error_when_fallback_exhausts(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "primary-exhausted.example.test" in str(request.url):
            return httpx.Response(503, json={"error": {"message": "primary unavailable"}})
        return httpx.Response(503, json={"error": {"message": "secondary unavailable"}})

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        primary_provider = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Primary exhausted",
                "base_url": "https://primary-exhausted.example.test/v1",
            },
        )
        secondary_provider = await client.post(
            "/api/v1/providers",
            headers=admin_headers,
            json={
                "name": "Secondary exhausted",
                "base_url": "https://secondary-exhausted.example.test/v1",
            },
        )
        assert primary_provider.status_code == 201
        assert secondary_provider.status_code == 201
        primary_pool_id, primary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=primary_provider.json()["id"],
            model="primary-exhausted-chat",
        )
        secondary_pool_id, secondary_model_id = await _create_provider_resources(
            client=client,
            headers=admin_headers,
            provider_id=secondary_provider.json()["id"],
            model="secondary-exhausted-chat",
        )
        team = await client.post(
            "/api/v1/teams",
            headers=admin_headers,
            json={"name": "Fallback Exhausted Team", "slug": "fallback-exhausted-team"},
        )
        project = await client.post(
            f"/api/v1/teams/{team.json()['id']}/projects",
            headers=admin_headers,
            json={"name": "Fallback Exhausted Project"},
        )
        access = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Fallback exhausted access",
                "public_models": [
                    {
                        "public_model_name": "chat-exhausted",
                        "routing_mode": "ordered_fallback",
                        "fallback_on": ["provider_5xx"],
                        "candidates": [
                            {
                                "provider_id": primary_provider.json()["id"],
                                "credential_pool_id": primary_pool_id,
                                "model_offering_id": primary_model_id,
                                "priority": 10,
                            },
                            {
                                "provider_id": secondary_provider.json()["id"],
                                "credential_pool_id": secondary_pool_id,
                                "model_offering_id": secondary_model_id,
                                "priority": 20,
                            },
                        ],
                    }
                ],
            },
        )
        assert access.status_code == 201
        assignment = await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": access.json()["policy_id"],
                "scope_type": "project",
                "project_id": project.json()["id"],
            },
        )
        assert assignment.status_code == 201
        key = await client.post(
            f"/api/v1/projects/{project.json()['id']}/keys",
            headers=admin_headers,
            json={"name": "Fallback exhausted key"},
        )

        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key.json()['key']}"},
            json={
                "model": "chat-exhausted",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:bab:error:provider-upstream"
    assert response.json()["status"] == 503
    assert response.json()["instance"] == "/v1/chat/completions"
    assert response.json()["failure_reason"] == "provider_5xx"
    assert response.json()["upstream_status"] == 503
    assert len(calls) == 2
    records = usage.json()["items"]
    assert [record["provider_model"] for record in records[:2]] == [
        "secondary-exhausted-chat",
        "primary-exhausted-chat",
    ]
    assert records[0]["is_final_attempt"] is True
    assert records[0]["attempt_failure_reason"] == "provider_5xx"
    assert records[0]["routing_attempt_index"] == 1
    assert records[1]["is_final_attempt"] is False
    assert records[1]["routing_attempt_index"] == 0
    assert records[0]["gateway_request_id"] == records[1]["gateway_request_id"]
    db_session.expire_all()
    gateway_requests = (await db_session.execute(select(GatewayRequest))).scalars().all()
    assert len(gateway_requests) == 1
    assert gateway_requests[0].attempt_count == 2
    assert gateway_requests[0].fallback_attempted is True
    assert gateway_requests[0].final_http_status == 503
    assert gateway_requests[0].final_provider_model == "secondary-exhausted-chat"
    assert gateway_requests[0].final_error_code == "provider_upstream_error"
    route_attempts = (
        (
            await db_session.execute(
                select(GatewayRouteAttempt).order_by(GatewayRouteAttempt.attempt_index)
            )
        )
        .scalars()
        .all()
    )
    usage_records = (
        (
            await db_session.execute(
                select(UsageRecord).order_by(UsageRecord.is_final_attempt.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [attempt.status for attempt in route_attempts] == ["failed", "failed"]
    assert usage_records[0].is_final_attempt is False
    assert usage_records[0].route_attempt_id == route_attempts[0].id
    assert usage_records[1].is_final_attempt is True
    assert usage_records[1].route_attempt_id == route_attempts[1].id
    assert gateway_requests[0].final_route_attempt_id == route_attempts[1].id
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_completion_does_not_fallback_for_nonfallbackable_status(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        (
            virtual_key,
            _primary_provider_id,
            _secondary_provider_id,
        ) = await _provision_ordered_fallback_gateway_path(
            client=client,
            headers=admin_headers,
            slug_suffix="nonfallbackable",
            public_model_name="chat-no-fallback",
        )
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "chat-no-fallback", "messages": [{"role": "user", "content": "hello"}]},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 400
    assert response.json()["type"] == "urn:bab:error:provider-upstream"
    assert response.json()["failure_reason"] == "provider_error"
    assert len(calls) == 1
    records = usage.json()["items"]
    assert len(records) == 1
    assert records[0]["is_final_attempt"] is True
    assert records[0]["attempt_failure_reason"] == "provider_error"
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_completion_falls_back_for_configured_rate_limit(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "primary-rate-limit.example.test" in str(request.url):
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_rate_limit_fallback",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "rate-limit-fallback-ok"},
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
        (
            virtual_key,
            _primary_provider_id,
            _secondary_provider_id,
        ) = await _provision_ordered_fallback_gateway_path(
            client=client,
            headers=admin_headers,
            slug_suffix="rate-limit",
            public_model_name="chat-rate-limit",
            fallback_on=["rate_limited"],
        )
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "chat-rate-limit", "messages": [{"role": "user", "content": "hello"}]},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "rate-limit-fallback-ok"
    assert len(calls) == 2
    records = usage.json()["items"]
    assert records[1]["attempt_failure_reason"] == "rate_limited"
    assert records[1]["is_final_attempt"] is False
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_responses_and_completions_fall_back_to_second_candidate(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(f"{request.url.host}:{body['model']}")
        if "primary-openai-compatible.example.test" in str(request.url):
            return httpx.Response(503, json={"error": {"message": "primary unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_openai_compatible_fallback",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "compatible-fallback-ok"},
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
        (
            virtual_key,
            _primary_provider_id,
            _secondary_provider_id,
        ) = await _provision_ordered_fallback_gateway_path(
            client=client,
            headers=admin_headers,
            slug_suffix="openai-compatible",
            public_model_name="chat-compatible",
        )
        responses_response = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "chat-compatible", "input": "hello"},
        )
        completions_response = await client.post(
            "/v1/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "chat-compatible", "prompt": "hello"},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert responses_response.status_code == 200
    assert responses_response.json()["output_text"] == "compatible-fallback-ok"
    assert completions_response.status_code == 200
    assert completions_response.json()["choices"][0]["text"] == "compatible-fallback-ok"
    assert calls == [
        "primary-openai-compatible.example.test:primary-openai-compatible-chat",
        "secondary-openai-compatible.example.test:secondary-openai-compatible-chat",
        "primary-openai-compatible.example.test:primary-openai-compatible-chat",
        "secondary-openai-compatible.example.test:secondary-openai-compatible-chat",
    ]
    records = usage.json()["items"]
    assert [record["gateway_endpoint"] for record in records[:4]] == [
        "completions",
        "completions",
        "responses",
        "responses",
    ]
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_responses_exhausted_fallback_records_response_endpoint(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            503,
            json={
                "error": {
                    "message": f"{request.url.host}:{body['model']} unavailable",
                    "type": "unavailable",
                }
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
        (
            virtual_key,
            _primary_provider_id,
            _secondary_provider_id,
        ) = await _provision_ordered_fallback_gateway_path(
            client=client,
            headers=admin_headers,
            slug_suffix="responses-exhausted",
            public_model_name="chat-responses-exhausted",
        )
        response = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "chat-responses-exhausted", "input": "hello"},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 503
    records = usage.json()["items"]
    assert [record["gateway_endpoint"] for record in records[:2]] == [
        "responses",
        "responses",
    ]
    assert records[0]["error_code"] == "provider_upstream_error"
    assert records[0]["is_final_attempt"] is True
    assert records[1]["is_final_attempt"] is False
    assert records[0]["gateway_request_id"] == records[1]["gateway_request_id"]
    app_client.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_completion_provider_pin_disables_fallback(
    app_client,
    db_session,
) -> None:
    await sync_default_workspace(db_session)
    calls: list[str] = []

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={"error": {"message": "pinned provider down"}})

    async def override_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override_proxy_http_client

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        admin_headers = await _login(client)
        (
            virtual_key,
            primary_provider_id,
            _secondary_provider_id,
        ) = await _provision_ordered_fallback_gateway_path(
            client=client,
            headers=admin_headers,
            slug_suffix="provider-pin",
            public_model_name="chat-pinned",
        )
        response = await client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {virtual_key}",
                "X-Bab-Provider-Id": primary_provider_id,
            },
            json={"model": "chat-pinned", "messages": [{"role": "user", "content": "hello"}]},
        )
        usage = await client.get("/api/v1/usage/records", headers=admin_headers)

    assert response.status_code == 503
    assert response.json()["type"] == "urn:bab:error:provider-upstream"
    assert response.json()["failure_reason"] == "provider_5xx"
    assert len(calls) == 1
    records = usage.json()["items"]
    assert len(records) == 1
    assert records[0]["provider_id"] == primary_provider_id
    assert records[0]["is_final_attempt"] is True
    assert records[0]["attempt_failure_reason"] == "provider_5xx"
    app_client.dependency_overrides.clear()


async def _provision_ordered_fallback_gateway_path(
    *,
    client: AsyncClient,
    headers: dict[str, str],
    slug_suffix: str,
    public_model_name: str,
    fallback_on: list[str] | None = None,
) -> tuple[str, str, str]:
    primary_provider = await client.post(
        "/api/v1/providers",
        headers=headers,
        json={
            "name": f"Primary {slug_suffix}",
            "base_url": f"https://primary-{slug_suffix}.example.test/v1",
        },
    )
    secondary_provider = await client.post(
        "/api/v1/providers",
        headers=headers,
        json={
            "name": f"Secondary {slug_suffix}",
            "base_url": f"https://secondary-{slug_suffix}.example.test/v1",
        },
    )
    assert primary_provider.status_code == 201
    assert secondary_provider.status_code == 201
    primary_pool_id, primary_model_id = await _create_provider_resources(
        client=client,
        headers=headers,
        provider_id=primary_provider.json()["id"],
        model=f"primary-{slug_suffix}-chat",
    )
    secondary_pool_id, secondary_model_id = await _create_provider_resources(
        client=client,
        headers=headers,
        provider_id=secondary_provider.json()["id"],
        model=f"secondary-{slug_suffix}-chat",
    )
    team = await client.post(
        "/api/v1/teams",
        headers=headers,
        json={"name": f"Fallback {slug_suffix} Team", "slug": f"fallback-{slug_suffix}-team"},
    )
    project = await client.post(
        f"/api/v1/teams/{team.json()['id']}/projects",
        headers=headers,
        json={"name": f"Fallback {slug_suffix} Project"},
    )
    access = await client.post(
        "/api/v1/policies/access",
        headers=headers,
        json={
            "name": f"Fallback {slug_suffix} access",
            "public_models": [
                {
                    "public_model_name": public_model_name,
                    "routing_mode": "ordered_fallback",
                    "fallback_on": fallback_on or ["provider_5xx"],
                    "candidates": [
                        {
                            "provider_id": primary_provider.json()["id"],
                            "credential_pool_id": primary_pool_id,
                            "model_offering_id": primary_model_id,
                            "priority": 10,
                        },
                        {
                            "provider_id": secondary_provider.json()["id"],
                            "credential_pool_id": secondary_pool_id,
                            "model_offering_id": secondary_model_id,
                            "priority": 20,
                        },
                    ],
                }
            ],
        },
    )
    assert access.status_code == 201
    assignment = await client.post(
        "/api/v1/policies/assignments",
        headers=headers,
        json={
            "policy_type": "access",
            "policy_id": access.json()["policy_id"],
            "scope_type": "project",
            "project_id": project.json()["id"],
        },
    )
    assert assignment.status_code == 201
    key = await client.post(
        f"/api/v1/projects/{project.json()['id']}/keys",
        headers=headers,
        json={"name": f"Fallback {slug_suffix} key"},
    )
    assert key.status_code == 201
    return key.json()["key"], primary_provider.json()["id"], secondary_provider.json()["id"]


async def _create_provider_resources(
    *,
    client: AsyncClient,
    headers: dict[str, str],
    provider_id: str,
    model: str,
) -> tuple[str, str]:
    credential = await client.post(
        f"/api/v1/providers/{provider_id}/credentials",
        headers=headers,
        json={"name": f"{model} key", "api_key": f"sk-{model}"},
    )
    assert credential.status_code == 201
    pool = await client.post(
        f"/api/v1/providers/{provider_id}/pools",
        headers=headers,
        json={"name": f"{model} pool", "selection_policy": "priority"},
    )
    assert pool.status_code == 201
    pool_credential = await client.post(
        f"/api/v1/providers/{provider_id}/pools/{pool.json()['id']}/credentials",
        headers=headers,
        json={"provider_credential_id": credential.json()["id"]},
    )
    assert pool_credential.status_code == 201
    offering = await client.post(
        f"/api/v1/providers/{provider_id}/offerings",
        headers=headers,
        json={
            "provider_model_name": model,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": {"chat": True, "streaming": True},
            "input_price_per_million_tokens": 100,
            "output_price_per_million_tokens": 200,
        },
    )
    assert offering.status_code == 201
    return pool.json()["id"], offering.json()["id"]


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

