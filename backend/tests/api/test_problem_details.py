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

    @router.get("/test/bad-gateway")
    async def bad_gateway():
        raise HTTPException(status_code=502, detail="Upstream failed")

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


def test_openapi_documents_problem_details_for_all_errors(app_client) -> None:
    schema = app_client.openapi()
    problem_schema = schema["components"]["schemas"]["ProblemDetail"]
    responses = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
    expected_content = {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
        }
    }

    assert set(problem_schema["required"]) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
    }
    assert problem_schema["additionalProperties"] is True
    assert responses["422"]["content"] == expected_content
    assert responses["default"]["content"] == expected_content
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ValidationError" not in schema["components"]["schemas"]

    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            for status_code, response in operation["responses"].items():
                if status_code == "default" or status_code.startswith(("4", "5")):
                    assert response["content"] == expected_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/definitely-missing", 404),
        ("POST", "/api/v1/health", 405),
        ("GET", "/assets/definitely-missing.png", 404),
        ("POST", "/v1/embeddings", 501),
    ],
)
async def test_framework_and_direct_errors_return_problem_details(
    app_client,
    method: str,
    path: str,
    expected_status: int,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path)

    body = response.json()
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["status"] == expected_status
    assert body["instance"] == path
    assert {"type", "title", "status", "detail", "instance"} <= body.keys()
    if expected_status == 405:
        assert response.headers["allow"] == "GET"


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
async def test_common_5xx_http_exception_uses_stable_problem_type(app_client) -> None:
    _add_problem_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/bad-gateway")

    assert response.status_code == 502
    assert response.json() == {
        "type": "urn:bab:error:bad-gateway",
        "title": "Bad Gateway",
        "status": 502,
        "detail": "Upstream failed",
        "instance": "/test/bad-gateway",
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
