from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.proxy import _enforce_allocation_limits, _record_proxy_request
from app.core.database import Scope
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import AccessDeniedError
from app.modules.keys.schemas import (
    AllocationOffering,
    CreateAllocationRequest,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessRequest,
    UpdateAllocationRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderRequest,
)
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import UsageAccounting


async def _create_actor_scope(db_session: AsyncSession):
    org = Organization(name=f"Allocation {uuid4()}", slug=f"allocation-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    db_session.add(team)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        team_id=team.id,
        email="admin@example.com",
        role="super_admin",
    )
    return actor, Scope(org_id=org.id), team


async def _create_project_pool_and_models(db_session: AsyncSession):
    actor, scope, team = await _create_actor_scope(db_session)
    project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Console", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="OpenAI", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Production"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fast_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="gpt-5.4-mini", alias="fast"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    large_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="gpt-5.5"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return actor, scope, team, project, provider, pool, fast_model, large_model


async def test_allocation_grants_pool_model_access(db_session: AsyncSession) -> None:
    actor, scope, _, project, provider, pool, fast_model, _ = await _create_project_pool_and_models(
        db_session
    )
    allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Console grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="gpt-5.4-mini",
        ),
        db=db_session,
    )

    assert resolved.provider_id == provider.id
    assert resolved.pool_id == pool.id
    assert resolved.provider_model == "gpt-5.4-mini"


async def test_allocation_denies_models_outside_offerings(db_session: AsyncSession) -> None:
    actor, scope, _, project, _, pool, fast_model, _ = await _create_project_pool_and_models(
        db_session
    )
    allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Console grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )


async def test_inactive_allocation_denies_access(db_session: AsyncSession) -> None:
    actor, scope, _, project, _, pool, fast_model, _ = await _create_project_pool_and_models(
        db_session
    )
    allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Console grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.update_allocation(
        allocation_id=allocation.id,
        payload=UpdateAllocationRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.4-mini"),
            db=db_session,
        )


async def test_project_allocation_must_respect_parent_route_at_runtime(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        _,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Team grant",
            team_id=team.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Project grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=large_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=project_allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )


async def test_inherited_key_uses_current_project_default_at_runtime(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _,
        project,
        _,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    first_allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="First project default",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inherited key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    second_allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Second project default",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=large_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
        db=db_session,
    )

    assert created_key.allocation_id == first_allocation.id
    assert resolved.allocation_id == second_allocation.id
    assert resolved.provider_model == "gpt-5.5"


async def test_key_custom_allocation_is_capped_by_current_team_default(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        _,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    custom_allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Project override",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=large_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(
            name="Custom key",
            allocation_id=custom_allocation.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Current team default",
            team_id=team.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )

    models = await keys_facade.list_accessible_models(raw_key=created_key.key, db=db_session)
    assert models == []


async def test_allocation_limits_apply_to_parent_chain(db_session: AsyncSession) -> None:
    actor, scope, team, project, _, pool, fast_model, _ = await _create_project_pool_and_models(
        db_session
    )
    await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Team grant",
            team_id=team.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
            max_requests=1,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Project grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=project_allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.4-mini"),
        db=db_session,
    )

    await _record_proxy_request(
        resolved=resolved,
        http_status=200,
        latency_ms=10,
        usage=UsageAccounting(
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            usage_source="provider_reported",
        ),
        error_code=None,
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        await _enforce_allocation_limits(
            resolved=resolved,
            estimated_input_tokens=1,
            requested_output_tokens=None,
            db=db_session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "allocation request limit exceeded"


async def test_allocation_usage_summary_breaks_down_usage(db_session: AsyncSession) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Project grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.4-mini"),
        db=db_session,
    )
    await _record_proxy_request(
        resolved=resolved,
        http_status=200,
        latency_ms=25,
        usage=UsageAccounting(
            prompt_tokens=7,
            completion_tokens=11,
            total_tokens=18,
            usage_source="provider_reported",
        ),
        error_code=None,
        db=db_session,
    )

    summary = await usage_facade.get_allocation_usage_summary(
        allocation_id=allocation.id,
        org_id=scope.org_id,
        db=db_session,
    )

    assert summary.totals.requests == 1
    assert summary.totals.total_tokens == 18
    assert summary.by_virtual_key[0].label == "Console key"
    assert summary.by_provider[0].label == provider.name
    assert summary.by_pool[0].label == pool.name
    assert summary.by_model[0].label == "gpt-5.4-mini"


async def test_organization_usage_summary_breaks_down_usage(db_session: AsyncSession) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    allocation = await keys_facade.create_allocation(
        payload=CreateAllocationRequest(
            name="Project grant",
            project_id=project.id,
            offerings=[AllocationOffering(pool_id=pool.id, model_offering_id=fast_model.id)],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key", allocation_id=allocation.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.4-mini"),
        db=db_session,
    )
    await _record_proxy_request(
        resolved=resolved,
        http_status=502,
        latency_ms=35,
        usage=UsageAccounting(
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
            usage_source="provider_reported",
        ),
        error_code="provider_upstream_error",
        db=db_session,
    )

    summary = await usage_facade.get_organization_usage_summary(
        org_id=scope.org_id,
        window="30d",
        db=db_session,
    )

    assert summary.totals.requests == 1
    assert summary.totals.failed_requests == 1
    assert summary.by_team[0].label == team.name
    assert summary.by_project[0].label == project.name
    assert summary.by_allocation[0].label == allocation.name
    assert summary.by_virtual_key[0].label == "Console key"
    assert summary.by_provider[0].label == provider.name
    assert summary.by_pool[0].label == pool.name
    assert summary.by_model[0].label == "gpt-5.4-mini"
