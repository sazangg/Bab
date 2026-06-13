"""Regression tests for the gateway proxy limit/reservation/body-size fixes."""

from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.v1.routes.proxy import get_proxy_http_client
from app.core.bootstrap import sync_default_workspace
from app.modules.usage.internal.models import LimitPolicyReservation
from tests.integration.test_gateway_flow import _login, _provision_gateway_path


def _ok_upstream() -> httpx.MockTransport:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-x",
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

    return httpx.MockTransport(handler)


def _override_upstream(app_client) -> None:
    async def override() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=_ok_upstream()) as client:
            yield client

    app_client.dependency_overrides[get_proxy_http_client] = override


# --- #4 body-size cap enforced before auth / before full buffering ----------


@pytest.mark.asyncio
async def test_oversized_body_is_rejected_before_auth(app_client, db_session, monkeypatch) -> None:
    await sync_default_workspace(db_session)
    monkeypatch.setattr("app.api.v1.routes.proxy.settings.proxy_max_body_bytes", 256)

    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        # No Authorization header: the size guard must fire before key auth.
        response = await client.post(
            "/v1/chat/completions",
            content=b"x" * 5000,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


# --- #7 a request-count denial must not leak earlier reservations -----------


@pytest.mark.asyncio
async def test_request_limit_denial_releases_token_reservation(app_client, db_session) -> None:
    await sync_default_workspace(db_session)
    _override_upstream(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _cred, _prov = await _provision_gateway_path(
            client,
            admin_headers,
            limit_payload={
                "rules": [
                    # An estimated-type limit (creates a reservation in phase 1)...
                    {
                        "name": "Tokens",
                        "limit_type": "input_tokens",
                        "limit_value": 1_000_000,
                        "interval_unit": "day",
                    },
                    # ...plus a requests limit that trips on the 2nd call.
                    {
                        "name": "OneRequest",
                        "limit_type": "requests",
                        "limit_value": 1,
                        "interval_unit": "day",
                    },
                ]
            },
        )
        payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}
        first = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json=payload,
        )
        assert first.status_code == 200
        denied = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json=payload,
        )
        assert denied.status_code == 429

    # The phase-1 token reservation from the denied request must have been released,
    # not left 'active' to count against the key until expiry.
    active = await db_session.scalar(
        select(func.count())
        .select_from(LimitPolicyReservation)
        .where(LimitPolicyReservation.status == "active")
    )
    assert active == 0


# --- #3 budget_cents fails closed for an unpriced model ---------------------


@pytest.mark.asyncio
async def test_budget_limit_fails_closed_when_model_unpriced(app_client, db_session) -> None:
    await sync_default_workspace(db_session)
    _override_upstream(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client), base_url="http://test"
    ) as client:
        admin_headers = await _login(client)
        virtual_key, _cred, _prov = await _provision_gateway_path(
            client,
            admin_headers,
            offering_payload={
                "input_price_per_million_tokens": None,
                "output_price_per_million_tokens": None,
            },
            limit_payload={
                "rules": [
                    {
                        "name": "Budget",
                        "limit_type": "budget_cents",
                        "limit_value": 100000,
                        "interval_unit": "day",
                    }
                ]
            },
        )
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {virtual_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    # Unpriced model under a budget cap must be denied, not silently allowed.
    assert response.status_code == 429
    assert "pricing" in response.json()["detail"]
