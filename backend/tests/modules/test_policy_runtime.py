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
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderRequest,
)


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
            max_requests=max_requests,
            max_tokens_per_request=max_tokens_per_request,
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


async def test_policy_runtime_requires_access_and_limit_before_key_creation(
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
