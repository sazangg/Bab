from typing import Annotated

import pytest
from fastapi import APIRouter, Body, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.core.problems import ProblemException


class ExamplePayload(BaseModel):
    name: str = Field(min_length=3)


def _add_problem_test_routes(app_client) -> None:
    router = APIRouter()

    @router.get("/test/http-error")
    async def http_error():
        raise HTTPException(status_code=404, detail="Example resource does not exist")

    @router.get("/test/problem-error")
    async def problem_error():
        raise ProblemException(
            problem_type="urn:bab:error:example",
            title="Example Error",
            status=409,
            detail="Example conflict",
        )

    @router.post("/test/validation-error")
    async def validation_error(payload: Annotated[ExamplePayload, Body()]):
        return payload

    @router.get("/test/unhandled-error")
    async def unhandled_error():
        raise RuntimeError("sensitive internals")

    app_client.include_router(router)


@pytest.mark.asyncio
async def test_http_exception_returns_problem_details(app_client) -> None:
    _add_problem_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/http-error")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:bab:error:not-found",
        "title": "Not Found",
        "status": 404,
        "detail": "Example resource does not exist",
        "instance": "/test/http-error",
    }


@pytest.mark.asyncio
async def test_problem_exception_keeps_specific_problem_type(app_client) -> None:
    _add_problem_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/problem-error")

    assert response.status_code == 409
    assert response.json() == {
        "type": "urn:bab:error:example",
        "title": "Example Error",
        "status": 409,
        "detail": "Example conflict",
        "instance": "/test/problem-error",
    }


@pytest.mark.asyncio
async def test_validation_error_returns_problem_details_with_errors(app_client) -> None:
    _add_problem_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/test/validation-error", json={"name": "ab"})

    body = response.json()

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["type"] == "urn:bab:error:validation-error"
    assert body["title"] == "Validation Error"
    assert body["status"] == 422
    assert body["detail"] == "Request validation failed"
    assert body["instance"] == "/test/validation-error"
    assert body["errors"][0]["loc"] == ["body", "name"]


@pytest.mark.asyncio
async def test_unhandled_error_returns_generic_problem_details(app_client) -> None:
    _add_problem_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/unhandled-error")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:bab:error:internal-server-error",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "An unexpected error occurred",
        "instance": "/test/unhandled-error",
    }
