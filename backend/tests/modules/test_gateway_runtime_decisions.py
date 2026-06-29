from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.gateway_history import facade as gateway_history_facade
from app.modules.gateway_history.internal import repository as gateway_history_repository
from app.modules.gateway_history.internal.models import (
    GatewayPolicyDecision,
    GatewayRequest,
    GatewayRouteAttempt,
)
from app.modules.gateway_history.schemas import CreateGatewayRequest, FinalizeGatewayRequest
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.keys.internal.models import VirtualKey
from app.modules.providers.internal.models import CredentialPool, Provider
from app.modules.usage.internal import records as usage_records
from app.modules.usage.schemas import RecordUsage
from app.modules.workspace.internal.models import Organization, Project, Team


async def test_gateway_runtime_decision_substrate_records_attempt_and_decision(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Gateway Trace Org", slug=f"gateway-trace-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Gateway Project",
        slug=f"gateway-project-{uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Gateway key",
        key_hash=uuid4().hex,
        key_prefix="bab_test",
    )
    db_session.add(virtual_key)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="Trace Provider",
        slug=f"trace-provider-{uuid4()}",
        base_url="https://provider.example.test",
    )
    db_session.add(provider)
    await db_session.flush()
    pool = CredentialPool(
        org_id=org.id,
        provider_id=provider.id,
        name="Trace Pool",
    )
    db_session.add(pool)
    await db_session.flush()

    gateway_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=org.id,
            team_id=team.id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )
    attempt = await gateway_history_repository.create_gateway_route_attempt(
        values={
            "org_id": org.id,
            "gateway_request_id": gateway_request.id,
            "attempt_index": 0,
            "status": "planned",
            "provider_model": "gpt-4o-mini",
            "public_model_name": "fast",
            "usage_source": "unknown",
            "pricing_snapshot": {"source": "catalog"},
            "capability_snapshot": {"streaming": True},
            "route_snapshot": {"routing_mode": "single_route"},
            "started_at": datetime.now(UTC),
        },
        db=db_session,
    )
    decision = await gateway_history_repository.create_gateway_policy_decision(
        values={
            "org_id": org.id,
            "gateway_request_id": gateway_request.id,
            "route_attempt_id": attempt.id,
            "decision_type": "provider_routing",
            "stage": "provider_attempt",
            "outcome": "selected",
            "enforced": True,
            "dimension_snapshot": {"public_model_name": "fast"},
            "metadata_": {"reason": "priority"},
        },
        db=db_session,
    )
    await gateway_history_repository.update_gateway_route_attempt(
        route_attempt_id=attempt.id,
        values={"status": "succeeded", "completed_at": datetime.now(UTC), "http_status": 200},
        db=db_session,
    )
    await gateway_history_repository.finalize_gateway_request(
        gateway_request_id=gateway_request.id,
        payload=FinalizeGatewayRequest(
            final_http_status=200,
            final_route_attempt_id=attempt.id,
            attempt_count=1,
        ),
        db=db_session,
    )

    stored_attempt = await db_session.scalar(
        select(GatewayRouteAttempt).where(GatewayRouteAttempt.id == attempt.id)
    )
    stored_decision = await db_session.scalar(
        select(GatewayPolicyDecision).where(GatewayPolicyDecision.id == decision.id)
    )

    assert gateway_request.trace_expires_at > gateway_request.started_at
    assert stored_attempt.status == "succeeded"
    assert stored_decision.metadata_ == {"reason": "priority"}
    assert stored_decision.dimension_snapshot == {"public_model_name": "fast"}


async def test_gateway_request_can_be_created_before_identity_resolution(
    db_session: AsyncSession,
) -> None:
    gateway_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )

    assert gateway_request.org_id is None
    assert gateway_request.team_id is None
    assert gateway_request.project_id is None
    assert gateway_request.virtual_key_id is None
    assert gateway_request.trace_expires_at > gateway_request.started_at


async def test_unresolved_gateway_request_can_be_finalized(
    db_session: AsyncSession,
) -> None:
    gateway_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )

    await gateway_history_repository.finalize_gateway_request(
        gateway_request_id=gateway_request.id,
        payload=FinalizeGatewayRequest(
            final_http_status=401,
            attempt_count=0,
            fallback_attempted=False,
            final_error_code="invalid_virtual_key",
        ),
        db=db_session,
    )
    stored = await db_session.scalar(
        select(GatewayRequest).where(GatewayRequest.id == gateway_request.id)
    )

    assert stored is not None
    assert stored.org_id is None
    assert stored.virtual_key_id is None
    assert stored.final_http_status == 401
    assert stored.final_error_code == "invalid_virtual_key"


async def test_gateway_request_trace_returns_runtime_rows(db_session: AsyncSession) -> None:
    org = Organization(name="Gateway Trace Read Org", slug=f"gateway-trace-read-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Gateway Project",
        slug=f"gateway-project-{uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Gateway key",
        key_hash=uuid4().hex,
        key_prefix="bab_test",
    )
    db_session.add(virtual_key)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="Trace Read Provider",
        slug=f"trace-read-provider-{uuid4()}",
        base_url="https://provider.example.test",
    )
    db_session.add(provider)
    await db_session.flush()
    pool = CredentialPool(
        org_id=org.id,
        provider_id=provider.id,
        name="Trace Read Pool",
    )
    db_session.add(pool)
    await db_session.flush()

    gateway_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=org.id,
            team_id=team.id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
            public_model_name="fast",
            routing_mode="single_route",
        ),
        db=db_session,
    )
    attempt = await gateway_history_repository.create_gateway_route_attempt(
        values={
            "org_id": org.id,
            "gateway_request_id": gateway_request.id,
            "attempt_index": 0,
            "status": "succeeded",
            "provider_model": "gpt-4o-mini",
            "public_model_name": "fast",
            "usage_source": "estimated",
            "pricing_snapshot": {"source": "catalog"},
            "capability_snapshot": {"streaming": True},
            "route_snapshot": {"routing_mode": "single_route"},
            "started_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
            "http_status": 200,
        },
        db=db_session,
    )
    await gateway_history_repository.create_gateway_policy_decision(
        values={
            "org_id": org.id,
            "gateway_request_id": gateway_request.id,
            "route_attempt_id": attempt.id,
            "decision_type": "provider_routing",
            "stage": "provider_attempt",
            "outcome": "selected",
            "enforced": True,
            "dimension_snapshot": {"public_model_name": "fast"},
            "metadata_": {"reason": "priority", "api_key": "sk-secret"},
        },
        db=db_session,
    )
    await guardrails_repository.create_event(
        org_id=org.id,
        policy_id=None,
        policy_revision_id=None,
        rule_id=None,
        decision="allowed",
        phase="request",
        reason="request_guardrails_passed",
        team_id=team.id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        provider_id=uuid4(),
        pool_id=uuid4(),
        request_id="req-trace",
        requested_model="fast",
        provider_model="gpt-4o-mini",
        metadata={"phase": "request", "prompt_text": "do not expose"},
        gateway_request_id=gateway_request.id,
        route_attempt_id=attempt.id,
        db=db_session,
    )
    await usage_records.create_usage_record(
        payload=RecordUsage(
            org_id=org.id,
            team_id=team.id,
            project_id=project.id,
            gateway_request_id=gateway_request.id,
            virtual_key_id=virtual_key.id,
            pool_id=pool.id,
            provider_id=provider.id,
            provider_credential_id=None,
            request_id="req-trace",
            requested_model="fast",
            provider_model="gpt-4o-mini",
            public_model_name="fast",
            http_status=200,
            latency_ms=42,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost_cents=1,
            cost_micro_cents=1_000_000,
            usage_source="estimated",
        ),
        db=db_session,
    )

    trace = await gateway_history_facade.get_gateway_request_trace(
        org_id=org.id,
        gateway_request_id=gateway_request.id,
        db=db_session,
    )

    assert trace is not None
    assert trace.request.id == gateway_request.id
    assert trace.route_attempts[0].id == attempt.id
    assert trace.timeline
    assert trace.timeline[0].kind == "request"
    assert {item.kind for item in trace.timeline} == {
        "request",
        "route_attempt",
        "policy_decision",
        "guardrail_event",
        "usage_record",
    }
    assert trace.policy_decisions[0].metadata == {
        "reason": "priority",
        "api_key": "[redacted]",
    }
    assert trace.guardrail_events[0].metadata == {
        "phase": "request",
        "prompt_text": "[redacted]",
    }
    assert trace.usage_records[0].total_tokens == 15


async def test_gateway_request_trace_hides_expired_trace(db_session: AsyncSession) -> None:
    org = Organization(name="Gateway Trace Expired Org", slug=f"gateway-trace-expired-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Gateway Project",
        slug=f"gateway-project-{uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Gateway key",
        key_hash=uuid4().hex,
        key_prefix="bab_test",
    )
    db_session.add(virtual_key)
    await db_session.flush()

    gateway_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=org.id,
            team_id=team.id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )
    gateway_request.trace_expires_at = datetime.now(UTC)
    await db_session.flush()

    trace = await gateway_history_facade.get_gateway_request_trace(
        org_id=org.id,
        gateway_request_id=gateway_request.id,
        db=db_session,
    )

    assert trace is None


async def test_gateway_request_list_batches_attempts_and_labels(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    org = Organization(name="Gateway List Batch Org", slug=f"gateway-list-batch-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="List Batch Provider",
        slug=f"list-batch-provider-{uuid4()}",
        base_url="https://provider.example.test",
    )
    db_session.add(provider)
    await db_session.flush()
    pool = CredentialPool(
        org_id=org.id,
        provider_id=provider.id,
        name="List Batch Pool",
    )
    db_session.add(pool)
    await db_session.flush()

    first_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=org.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )
    first_attempt = await gateway_history_repository.create_gateway_route_attempt(
        values={
            "org_id": org.id,
            "gateway_request_id": first_request.id,
            "attempt_index": 0,
            "status": "succeeded",
            "provider_id": provider.id,
            "credential_pool_id": pool.id,
            "provider_model": "gpt-4o-mini",
            "usage_source": "unknown",
            "pricing_snapshot": {},
            "capability_snapshot": {},
            "route_snapshot": {},
            "started_at": datetime.now(UTC),
        },
        db=db_session,
    )
    await gateway_history_repository.finalize_gateway_request(
        gateway_request_id=first_request.id,
        payload=FinalizeGatewayRequest(
            final_http_status=200,
            final_route_attempt_id=first_attempt.id,
            final_provider_id=provider.id,
            final_credential_pool_id=pool.id,
            attempt_count=1,
        ),
        db=db_session,
    )
    second_request = await gateway_history_repository.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=org.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )
    await gateway_history_repository.finalize_gateway_request(
        gateway_request_id=second_request.id,
        payload=FinalizeGatewayRequest(
            final_http_status=503,
            final_provider_id=provider.id,
            final_credential_pool_id=pool.id,
            attempt_count=0,
            final_error_code="provider_unavailable",
        ),
        db=db_session,
    )
    await db_session.commit()

    calls = {"batch_attempts": 0, "single_attempts": 0, "providers": 0, "pools": 0}
    original_batch_attempts = (
        gateway_history_facade.repository.list_gateway_route_attempts_for_requests
    )
    original_single_attempts = gateway_history_facade.repository.list_gateway_route_attempts
    original_provider_labels = gateway_history_facade.provider_read_models.get_provider_labels
    original_pool_labels = gateway_history_facade.provider_read_models.get_credential_pool_labels

    async def counted_batch_attempts(**kwargs):
        calls["batch_attempts"] += 1
        return await original_batch_attempts(**kwargs)

    async def counted_single_attempts(**kwargs):
        calls["single_attempts"] += 1
        return await original_single_attempts(**kwargs)

    async def counted_provider_labels(**kwargs):
        calls["providers"] += 1
        return await original_provider_labels(**kwargs)

    async def counted_pool_labels(**kwargs):
        calls["pools"] += 1
        return await original_pool_labels(**kwargs)

    monkeypatch.setattr(
        gateway_history_facade.repository,
        "list_gateway_route_attempts_for_requests",
        counted_batch_attempts,
    )
    monkeypatch.setattr(
        gateway_history_facade.repository,
        "list_gateway_route_attempts",
        counted_single_attempts,
    )
    monkeypatch.setattr(
        gateway_history_facade.provider_read_models,
        "get_provider_labels",
        counted_provider_labels,
    )
    monkeypatch.setattr(
        gateway_history_facade.provider_read_models,
        "get_credential_pool_labels",
        counted_pool_labels,
    )

    response = await gateway_history_facade.list_gateway_requests(
        org_id=org.id,
        window="24h",
        start_at=None,
        end_at=None,
        team_id=None,
        project_id=None,
        virtual_key_id=None,
        provider_id=None,
        public_model_name=None,
        requested_model=None,
        request_id=None,
        status=None,
        fallback=None,
        error_code=None,
        search=None,
        allowed_team_ids=None,
        allowed_project_ids=None,
        limit=10,
        offset=0,
        db=db_session,
    )

    assert {item.id for item in response.items} == {first_request.id, second_request.id}
    assert calls == {
        "batch_attempts": 1,
        "single_attempts": 0,
        "providers": 1,
        "pools": 1,
    }
    first_item = next(item for item in response.items if item.id == first_request.id)
    second_item = next(item for item in response.items if item.id == second_request.id)
    assert first_item.involved_provider_names == ["List Batch Provider"]
    assert second_item.final_provider_name == "List Batch Provider"
    assert second_item.final_credential_pool_name == "List Batch Pool"
