import warnings

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SAWarning
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.routes import health as health_routes
from app.core.database import Base
from app.core.migrations import run_database_migrations
from app.core.model_imports import import_all_models
from app.core.redis_client import RedisStorageError
from app.main import create_app


@pytest.mark.asyncio
async def test_health_check_returns_ok() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/health")
        root_response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert root_response.status_code == 200
    assert root_response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_id_header_is_preserved() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/health", headers={"X-Request-ID": "req-test"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test"


def test_model_metadata_sorts_gateway_trace_tables_without_fk_cycle_warning() -> None:
    import_all_models()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            message="Cannot correctly sort tables.*",
            category=SAWarning,
        )
        list(Base.metadata.sorted_tables)


@pytest.mark.asyncio
async def test_readiness_reports_database_and_migrations() -> None:
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await run_database_migrations(test_engine)
    original_engine = health_routes.engine
    health_routes.engine = test_engine
    app = create_app()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/v1/ready")
            readyz_response = await client.get("/readyz")
    finally:
        health_routes.engine = original_engine
        await test_engine.dispose()

    assert response.status_code == 200
    assert readyz_response.status_code == 200
    body = response.json()
    readyz_body = readyz_response.json()
    assert body["status"] == "ready"
    assert readyz_body["status"] == "ready"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["migrations"]["ok"] is True
    assert "redis" not in body["checks"]


@pytest.mark.asyncio
async def test_readiness_checks_enabled_redis(monkeypatch) -> None:
    async def healthy_storage() -> None:
        return None

    monkeypatch.setattr(health_routes.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(health_routes, "ping_redis", healthy_storage)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/ready")
        readyz_response = await client.get("/readyz")

    assert response.json()["checks"]["redis"] == {"ok": True}
    assert readyz_response.json()["checks"]["redis"] == {"ok": True}


@pytest.mark.asyncio
async def test_readiness_checks_provider_runtime_redis(monkeypatch) -> None:
    async def healthy_storage() -> None:
        return None

    monkeypatch.setattr(
        health_routes.settings,
        "provider_runtime_state_backend",
        "redis",
    )
    monkeypatch.setattr(health_routes, "ping_redis", healthy_storage)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/ready")

    assert response.json()["checks"]["redis"] == {"ok": True}


@pytest.mark.asyncio
async def test_readiness_safely_reports_unavailable_redis(monkeypatch) -> None:
    async def unavailable_storage() -> None:
        raise RedisStorageError("redis://user:secret@private-host")

    monkeypatch.setattr(health_routes.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(health_routes, "ping_redis", unavailable_storage)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["checks"]["redis"] == {
        "ok": False,
        "error": "RedisStorageError",
    }
    assert "private-host" not in response.text


@pytest.mark.asyncio
async def test_readiness_failure_returns_problem_details(monkeypatch) -> None:
    async def unavailable_migration_state(_engine):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(health_routes, "get_migration_state", unavailable_migration_state)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/ready")
        readyz_response = await client.get("/readyz")

    for result, path in ((response, "/api/v1/ready"), (readyz_response, "/readyz")):
        body = result.json()
        assert result.status_code == 503
        assert result.headers["content-type"].startswith("application/problem+json")
        assert body["status"] == 503
        assert body["instance"] == path
        assert body["readiness_status"] == "not_ready"
        assert body["checks"]["migrations"] == {"ok": False, "error": "RuntimeError"}


@pytest.mark.asyncio
async def test_runtime_info_returns_safe_runtime_summary() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/runtime-info")
        root_response = await client.get("/runtime-info")

    assert response.status_code == 200
    assert root_response.status_code == 404
    body = response.json()
    assert body["app_name"]
    assert body["app_version"]
    assert body["environment"] in {"development", "test", "production"}
    assert "migrations" in body
    assert "current_revision" in body["migrations"]
    assert "head_revision" in body["migrations"]
    assert "database_url" not in body
    assert "secret_key" not in body
