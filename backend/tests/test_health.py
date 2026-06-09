import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.routes import health as health_routes
from app.core.migrations import run_database_migrations
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
    assert "database_url" not in body
    assert "secret_key" not in body
