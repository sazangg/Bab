from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.proxy import _enforce_limit_policies
from app.core.database import Scope
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import AccessDeniedError, PolicyNotConfiguredError
from app.modules.keys.schemas import (
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessRequest,
)
from app.modules.policies import facade as policies_facade
from app.modules.policies.schemas import (
    AccessPolicyRouteInput,
    CreateAccessPolicyRequest,
    CreateLimitPolicyRequest,
    CreatePolicyAssignmentRequest,
    LimitPolicyRuleInput,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderRequest,
)
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import RecordUsage


async def _create_project_pool_and_models(db_session: AsyncSession):
    org = Organization(name=f"Policy {uuid4()}", slug=f"policy-{uuid4()}")
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
    scope = Scope(org_id=org.id)
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
        payload=CreateModelOfferingRequest(
            provider_model_name="gpt-5.4-mini",
            alias="fast",
            input_price_per_million_tokens=1_000_000,
            output_price_per_million_tokens=1_000_000,
        ),
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


async def _assign_access_and_limit(
    *,
    scope: Scope,
    team_id,
    project_id,
    provider_id,
    pool_id,
    model_ids,
    db_session: AsyncSession,
    scope_type: str = "project",
    max_requests: int | None = None,
    max_tokens_per_request: int | None = None,
):
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name=f"{scope_type} access",
            routes=[
                AccessPolicyRouteInput(
                    provider_id=provider_id,
                    credential_pool_id=pool_id,
                    model_offering_ids=model_ids,
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name=f"{scope_type} limits",
            rules=[
                rule
                for rule in (
                    LimitPolicyRuleInput(
                        name="Request cap",
                        limit_type="requests",
                        limit_value=max_requests,
                        interval_unit="day",
                    )
                    if max_requests is not None
                    else None,
                    LimitPolicyRuleInput(
                        name="Tokens per request",
                        limit_type="tokens_per_request",
                        limit_value=max_tokens_per_request,
                        interval_unit="lifetime",
                    )
                    if max_tokens_per_request is not None
                    else None,
                )
                if rule is not None
            ],
        ),
        scope=scope,
        db=db_session,
    )
    target = {"team_id": team_id} if scope_type == "team" else {"project_id": project_id}
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=access.id,
            scope_type=scope_type,
            **target,
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            limit_policy_id=limit.id,
            scope_type=scope_type,
            **target,
        ),
        scope=scope,
        db=db_session,
    )
    return access, limit


async def test_policy_runtime_grants_pool_model_access(db_session: AsyncSession) -> None:
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    access, _limit = await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )

    assert resolved.access_policy_id == access.id
    assert resolved.provider_id == provider.id
    assert resolved.pool_id == pool.id
    assert resolved.provider_model == "gpt-5.4-mini"


async def test_policy_runtime_requires_access_before_key_creation(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team, project, _provider, _pool, _fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )

    with pytest.raises(PolicyNotConfiguredError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Console key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_project_access_policy_is_capped_by_team_policy(
    db_session: AsyncSession,
) -> None:
    actor, scope, team, project, provider, pool, fast_model, large_model = (
        await _create_project_pool_and_models(db_session)
    )
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
        scope_type="team",
    )
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id, large_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    accessible_models = await keys_facade.list_project_accessible_models(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )

    assert [model.id for model in accessible_models] == ["gpt-5.4-mini"]
    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="gpt-5.5",
            ),
            db=db_session,
        )


async def test_limit_policy_request_limit_is_enforced(db_session: AsyncSession) -> None:
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        await _enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=1,
            requested_output_tokens=1,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request token limit exceeded"


async def test_reused_limit_policy_counts_per_assignment(db_session: AsyncSession) -> None:
    actor, scope, team, first_project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    second_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Second Console", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Shared access",
            routes=[
                AccessPolicyRouteInput(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_ids=[fast_model.id],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Reusable one request",
            rules=[
                LimitPolicyRuleInput(
                    name="One request",
                    limit_type="requests",
                    limit_value=1,
                    interval_unit="day",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    for project in (first_project, second_project):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                access_policy_id=access.id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="limit",
                limit_policy_id=limit.id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )

    first_key = await keys_facade.create_virtual_key(
        project_id=first_project.id,
        payload=CreateVirtualKeyRequest(name="First key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    second_key = await keys_facade.create_virtual_key(
        project_id=second_project.id,
        payload=CreateVirtualKeyRequest(name="Second key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    first_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=first_key.key, requested_model="fast"),
        db=db_session,
    )
    second_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=second_key.key, requested_model="fast"),
        db=db_session,
    )
    first_limit = first_resolved.limit_policies[0]

    await usage_facade.record_usage(
        payload=RecordUsage(
            org_id=first_resolved.org_id,
            team_id=first_resolved.team_id,
            project_id=first_resolved.project_id,
            access_policy_id=first_resolved.access_policy_id,
            access_policy_route_id=first_resolved.access_policy_route_id,
            limit_policy_ids=[str(first_limit.limit_policy_id)],
            limit_policy_rule_ids=[str(first_limit.limit_policy_rule_id)],
            limit_policy_assignment_ids=[str(first_limit.limit_policy_assignment_id)],
            virtual_key_id=first_resolved.virtual_key_id,
            pool_id=first_resolved.pool_id,
            provider_id=first_resolved.provider_id,
            provider_credential_id=None,
            requested_model=first_resolved.requested_model,
            provider_model=first_resolved.provider_model,
            http_status=200,
            latency_ms=10,
            prompt_tokens=1,
            completion_tokens=0,
            total_tokens=1,
            cost_cents=0,
            usage_source="test",
        ),
        db=db_session,
    )

    await _enforce_limit_policies(
        resolved=second_resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )
    with pytest.raises(HTTPException) as exc:
        await _enforce_limit_policies(
            resolved=first_resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"
