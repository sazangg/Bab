import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core import bootstrap
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    GuardrailRuleInput,
)
from app.modules.policies.schemas import (
    AccessPolicyPublicModelInput,
    LimitPolicyRuleInput,
)


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_policy_and_guardrail_metadata_require_authentication(
    app_client,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        policy_response = await client.get("/api/v1/policies/metadata")
        guardrail_response = await client.get("/api/v1/guardrails/metadata")

    assert policy_response.status_code == 401
    assert guardrail_response.status_code == 401


@pytest.mark.asyncio
async def test_policy_and_guardrail_metadata_return_domain_defaults(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "owner@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client, "owner@example.com", "correct-password")
        policy_response = await client.get("/api/v1/policies/metadata", headers=headers)
        guardrail_response = await client.get("/api/v1/guardrails/metadata", headers=headers)

    assert policy_response.status_code == 200
    assert policy_response.json() == {
        "routing_modes": ["single_route", "ordered_fallback"],
        "default_routing_mode": "single_route",
        "fallback_reasons": [
            "circuit_open",
            "connection_failed",
            "provider_5xx",
            "rate_limited",
            "timeout",
        ],
        "default_route_priority": 100,
        "default_route_weight": 100,
        "limit_types": [
            "budget_cents",
            "requests",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "tokens_per_request",
        ],
        "interval_units": ["minute", "hour", "day", "week", "month", "lifetime"],
        "default_interval_unit": "month",
        "default_interval_count": 1,
    }
    assert guardrail_response.status_code == 200
    assert guardrail_response.json() == {
        "rule_types": ["prompt_contains", "prompt_regex", "pii"],
        "pii_values": ["credit_card", "email", "phone"],
        "phases": ["request", "response", "both"],
        "effects": ["allow", "deny"],
        "policy_enforcement_modes": ["enforce", "monitor"],
        "assignment_enforcement_modes": ["enforce", "dry_run"],
        "default_rule_effect": "allow",
        "default_rule_phase": "both",
        "default_rule_priority": 100,
        "default_policy_enforcement_mode": "enforce",
        "default_assignment_enforcement_mode": "enforce",
    }


def test_metadata_values_remain_aligned_with_schema_validation() -> None:
    with pytest.raises(ValidationError):
        AccessPolicyPublicModelInput.model_validate(
            {
                "public_model_name": "invalid",
                "routing_mode": "random",
                "candidates": [],
            }
        )
    with pytest.raises(ValidationError):
        LimitPolicyRuleInput(
            name="invalid",
            limit_type="unknown",
            limit_value=1,
        )
    with pytest.raises(ValidationError):
        GuardrailRuleInput(
            rule_type="unknown",
            values=["value"],
        )
    with pytest.raises(ValidationError):
        CreateGuardrailAssignmentRequest(
            policy_id="00000000-0000-0000-0000-000000000001",
            scope_type="org",
            enforcement_mode="monitor",
        )
