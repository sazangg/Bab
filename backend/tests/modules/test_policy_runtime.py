from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.projects import create_virtual_key as create_virtual_key_route
from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    User,
)
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.gateway import accounting as gateway_accounting
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import tracing as gateway_tracing
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.internal.models import GuardrailEvent, GuardrailPolicy, GuardrailRule
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    GuardrailRuleInput,
)
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    PolicyNotConfiguredError,
    ProjectAccessUnavailableError,
    ProjectInactiveError,
    ProjectNotFoundError,
    SecretDeliveryDisabledError,
    VirtualKeyAlreadyRevokedError,
    VirtualKeyNotFoundError,
    VirtualKeyOverlapActiveError,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.schemas import (
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessPlanForVirtualKeyRequest,
    ResolveAccessRequest,
    RotateVirtualKeyRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
)
from app.modules.policies import facade as policies_facade
from app.modules.policies.errors import (
    PolicyAssignmentConflictError,
    PolicyNotFoundError,
    PolicyPermissionError,
    PolicyValidationError,
)
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.policies.runtime_limits import (
    RuntimeLimitEvaluationInput,
    evaluate_runtime_limits_readonly,
)
from app.modules.policies.schemas import (
    AccessPolicyPublicModelInput,
    AccessPolicyRouteCandidateInput,
    CreateAccessPolicyRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    LimitPolicyRuleInput,
    LimitPolicyRuleMatcherInput,
    LimitPolicyRulePartitionInput,
    UpdateAccessPolicyRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)
from app.modules.policy_kernel import assignment_scope_target_key
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import Policy, PolicyAssignment, PolicyRevision
from app.modules.policy_simulation.draft_validation import validate_policy_simulation_drafts
from app.modules.policy_simulation.errors import PolicySimulationValidationError
from app.modules.policy_simulation.schemas import (
    PolicySimulationRequest,
    PolicySimulationTarget,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal.models import Provider
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateProviderCredentialRequest,
    CreateProviderModelOfferingRequest,
    CreateProviderRequest,
    UpdateCredentialPoolRequest,
    UpdateProviderModelOfferingRequest,
    UpdateProviderRequest,
)
from app.modules.settings import facade as settings_facade
from app.modules.settings.schemas import UpdateOrganizationSettingsRequest
from app.modules.teams.errors import TeamInactiveError
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import unknown_usage
from app.modules.usage.internal.models import (
    GatewayPolicyDecision,
    GatewayRouteAttempt,
    LimitPolicyReservation,
    UsageRecord,
)
from app.modules.usage.schemas import CreateGatewayRequest, RecordUsage
from app.modules.workspace.internal.models import Team


def _public_model_route(
    *,
    provider_id,
    credential_pool_id,
    model_offering_id,
    public_model_name: str | None = None,
    priority: int = 100,
    weight: int = 100,
    is_active: bool = True,
) -> AccessPolicyPublicModelInput:
    if isinstance(model_offering_id, list):
        if len(model_offering_id) != 1:
            raise ValueError("Use one public model input per model offering.")
        model_offering_id = model_offering_id[0]
    return AccessPolicyPublicModelInput(
        public_model_name=public_model_name or str(model_offering_id),
        routing_mode="single_route",
        candidates=[
            AccessPolicyRouteCandidateInput(
                provider_id=provider_id,
                credential_pool_id=credential_pool_id,
                model_offering_id=model_offering_id,
                priority=priority,
                weight=weight,
                is_active=is_active,
            )
        ],
    )


async def _create_project_pool_and_models(db_session: AsyncSession):
    org = Organization(name=f"Policy {uuid4()}", slug=f"policy-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    db_session.add(team)
    await db_session.commit()
    actor_id = uuid4()
    actor_email = f"admin-{actor_id}@example.com"
    db_session.add(User(id=actor_id, email=actor_email, name="Policy Admin"))
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            org_id=org.id,
            user_id=actor_id,
            role="super_admin",
            status="active",
        )
    )
    await db_session.commit()
    actor = AuthenticatedUser(
        id=actor_id,
        org_id=org.id,
        team_id=team.id,
        email=actor_email,
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
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Runtime", api_key="runtime-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fast_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateProviderModelOfferingRequest(
            provider_model_name="gpt-5.4-mini",
            input_price_per_million_tokens=1_000_000,
            output_price_per_million_tokens=1_000_000,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    large_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateProviderModelOfferingRequest(provider_model_name="gpt-5.5"),
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
            public_models=[
                _public_model_route(
                    provider_id=provider_id,
                    credential_pool_id=pool_id,
                    model_offering_id=model_id,
                    public_model_name="fast" if index == 0 else str(model_id),
                )
                for index, model_id in enumerate(model_ids)
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
            policy_id=access.policy_id,
            scope_type=scope_type,
            **target,
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type=scope_type,
            **target,
        ),
        scope=scope,
        db=db_session,
    )
    return access, limit


async def _record_usage_for_resolved(
    *,
    resolved,
    db_session: AsyncSession,
    cost_cents: int = 0,
    http_status: int = 200,
    error_code: str | None = None,
) -> None:
    limit = resolved.limit_policies[0] if resolved.limit_policies else None
    await usage_facade.record_usage(
        payload=RecordUsage(
            org_id=resolved.org_id,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            access_policy_id=resolved.access_policy_id,
            access_policy_route_id=resolved.access_policy_route_id,
            limit_policy_ids=[str(limit.limit_policy_id)] if limit else [],
            limit_policy_rule_ids=[str(limit.limit_policy_rule_id)] if limit else [],
            limit_policy_assignment_ids=[str(limit.limit_policy_assignment_id)] if limit else [],
            virtual_key_id=resolved.virtual_key_id,
            pool_id=resolved.pool_id,
            provider_id=resolved.provider_id,
            provider_credential_id=None,
            requested_model=resolved.requested_model,
            provider_model=resolved.provider_model,
            http_status=http_status,
            latency_ms=10,
            prompt_tokens=1,
            completion_tokens=0,
            total_tokens=1,
            cost_cents=cost_cents,
            usage_source="test",
            error_code=error_code,
        ),
        db=db_session,
    )


async def _draft_side_effect_counts(db_session: AsyncSession) -> dict[str, int]:
    models = [
        Policy,
        PolicyRevision,
        PolicyAssignment,
        AccessPolicy,
        AccessPolicyPublicModel,
        AccessPolicyRouteCandidate,
        LimitPolicy,
        LimitPolicyRule,
        GuardrailPolicy,
        GuardrailRule,
        GuardrailEvent,
        LimitPolicyReservation,
    ]
    return {
        model.__tablename__: await db_session.scalar(select(func.count(model.id)))
        for model in models
    }


async def test_policy_runtime_grants_pool_model_access(db_session: AsyncSession) -> None:
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

    stored_access = await policies_repository.get_access_policy(
        policy_id=access.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert stored_access is not None
    assert resolved.access_policy_id == stored_access.policy_id
    assert resolved.provider_id == provider.id
    assert resolved.pool_id == pool.id
    assert resolved.provider_model == "gpt-5.4-mini"

    key = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        scope=scope,
        db=db_session,
    )
    assert key.created_by == actor.id
    assert key.creator_name == "Policy Admin"
    assert key.creator_email == actor.email
    assert key.last_used_at is not None
    assert "key_hash" not in key.model_dump()
    assert "key" not in key.model_dump()


async def test_policy_runtime_resolves_shared_access_policy_revision(
    db_session: AsyncSession,
) -> None:
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
    policy = await policy_kernel_repository.create_policy(
        org_id=scope.org_id,
        kind="access",
        name="Shared access",
        description=None,
        is_active=True,
        db=db_session,
    )
    revision = await policy_kernel_repository.create_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.id,
        revision_number=1,
        status="active",
        created_by=actor.id,
        db=db_session,
    )
    public_model = await policies_repository.create_access_policy_public_model(
        org_id=scope.org_id,
        access_policy_id=None,
        policy_revision_id=revision.id,
        public_model_name="fast",
        routing_mode="single_route",
        fallback_on=[],
        max_route_attempts=None,
        is_active=True,
        db=db_session,
    )
    candidate = await policies_repository.create_access_policy_route_candidate(
        org_id=scope.org_id,
        public_model_id=public_model.id,
        provider_id=provider.id,
        credential_pool_id=pool.id,
        model_offering_id=fast_model.id,
        priority=100,
        weight=100,
        is_active=True,
        db=db_session,
    )
    await policy_kernel_repository.create_policy_assignment(
        org_id=scope.org_id,
        values={
            "policy_id": policy.id,
            "policy_type": "access",
            "scope_type": "team",
            "team_id": team.id,
            "scope_target_key": assignment_scope_target_key(
                scope_type="team",
                team_id=team.id,
                project_id=None,
                virtual_key_id=None,
            ),
            "mode": "enforce",
            "is_active": True,
        },
        db=db_session,
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

    assert resolved.access_policy_id == policy.id
    assert resolved.access_policy_revision_id == revision.id
    assert resolved.public_model_id == public_model.id
    assert resolved.route_candidate_id == candidate.id
    assert resolved.provider_id == provider.id
    assert resolved.pool_id == pool.id
    assert resolved.model_offering_id == fast_model.id


async def test_facade_assignment_resolves_active_revision_and_traces_it(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Facade shared access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=access.policy_id,
        db=db_session,
    )
    assert active_revision is not None
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="team",
            team_id=team.id,
            mode="enforce",
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Revision trace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )

    assert resolved.access_policy_id == access.policy_id
    assert resolved.access_policy_revision_id == active_revision.id
    assert resolved.access_policy_assignment_id == assignment.id

    gateway_request_id = await gateway_tracing.create_gateway_request(
        resolved=resolved,
        gateway_endpoint="chat_completions",
        db=db_session,
    )
    assert gateway_request_id is not None
    await gateway_tracing.record_gateway_access_decision(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        db=db_session,
    )
    route_attempt_id = await gateway_tracing.record_gateway_route_attempt_started(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        attempt_index=0,
        db=db_session,
    )
    assert route_attempt_id is not None
    await db_session.flush()

    attempt = await db_session.scalar(
        select(GatewayRouteAttempt).where(GatewayRouteAttempt.id == route_attempt_id)
    )
    decisions = (
        await db_session.scalars(
            select(GatewayPolicyDecision).where(
                GatewayPolicyDecision.gateway_request_id == gateway_request_id
            )
        )
    ).all()
    assert attempt is not None
    assert attempt.access_policy_id == access.policy_id
    assert attempt.access_policy_revision_id == active_revision.id
    assert {decision.policy_revision_id for decision in decisions} == {active_revision.id}

    await policies_facade.update_access_policy(
        policy_id=access.id,
        payload=UpdateAccessPolicyRequest(
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=large_model.id,
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    new_active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=access.policy_id,
        db=db_session,
    )

    assert new_active_revision is not None
    assert new_active_revision.id != active_revision.id
    await db_session.refresh(attempt)
    refreshed_decisions = (
        await db_session.scalars(
            select(GatewayPolicyDecision).where(
                GatewayPolicyDecision.gateway_request_id == gateway_request_id
            )
        )
    ).all()
    assert attempt.access_policy_revision_id == active_revision.id
    assert {decision.policy_revision_id for decision in refreshed_decisions} == {active_revision.id}


async def test_access_policy_create_update_publishes_shared_revisions(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        _project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Dual write access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    legacy_policy = await policies_repository.get_access_policy(
        policy_id=access.id,
        org_id=scope.org_id,
        db=db_session,
    )
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=legacy_policy.policy_id,
        db=db_session,
    )
    revision_models = await policies_repository.list_access_policy_revision_public_models(
        org_id=scope.org_id,
        policy_revision_id=active_revision.id,
        db=db_session,
    )

    assert active_revision.revision_number == 1
    assert [item.public_model_name for item in revision_models] == ["fast"]

    await policies_facade.update_access_policy(
        policy_id=access.id,
        payload=UpdateAccessPolicyRequest(
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=large_model.id,
                    public_model_name="large",
                )
            ],
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    next_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=legacy_policy.policy_id,
        db=db_session,
    )
    old_revision_models = await policies_repository.list_access_policy_revision_public_models(
        org_id=scope.org_id,
        policy_revision_id=active_revision.id,
        db=db_session,
    )
    next_revision_models = await policies_repository.list_access_policy_revision_public_models(
        org_id=scope.org_id,
        policy_revision_id=next_revision.id,
        db=db_session,
    )

    assert active_revision.status == "archived"
    assert next_revision.revision_number == 2
    assert [item.public_model_name for item in old_revision_models] == ["fast"]
    assert [item.public_model_name for item in next_revision_models] == ["large"]


async def test_authenticated_key_use_is_recorded_before_policy_denial(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
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
        payload=CreateVirtualKeyRequest(name="Denied model key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="not-permitted",
            ),
            db=db_session,
        )

    key = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        scope=scope,
        db=db_session,
    )
    assert key.last_used_at is not None


async def test_revocation_records_actor_reason_and_is_irreversible(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
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
        payload=CreateVirtualKeyRequest(name="Revoked key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await keys_facade.revoke_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        reason="Application credential was replaced",
        actor=actor,
        scope=scope,
        db=db_session,
    )
    key = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        scope=scope,
        db=db_session,
    )

    assert key.revoked_at is not None
    assert key.revoked_by == actor.id
    assert key.revoker_name == "Policy Admin"
    assert key.revoker_email == actor.email
    assert key.revoked_reason == "Application credential was replaced"
    with pytest.raises(InvalidVirtualKeyError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
        )


async def test_rotation_keeps_both_keys_active_and_guards_early_revocation(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    old_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Rotating key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    new_key = await keys_facade.rotate_virtual_key(
        project_id=project.id,
        key_id=old_key.id,
        payload=RotateVirtualKeyRequest(name="Replacement key", overlap_days=7),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    assert new_key.supersedes_key_id == old_key.id
    for raw_key in (old_key.key, new_key.key):
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=raw_key, requested_model="fast"),
            db=db_session,
        )
        assert resolved.project_id == project.id

    with pytest.raises(VirtualKeyOverlapActiveError):
        await keys_facade.revoke_virtual_key(
            project_id=project.id,
            key_id=old_key.id,
            reason="Rotation completed early",
            actor=actor,
            scope=scope,
            db=db_session,
        )
    await keys_facade.revoke_virtual_key(
        project_id=project.id,
        key_id=old_key.id,
        reason="Rotation completed early",
        actor=actor,
        scope=scope,
        db=db_session,
        force=True,
    )


async def test_virtual_key_events_are_safe_and_failure_does_not_emit_success(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
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
        payload=CreateVirtualKeyRequest(name="Event key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.update_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        payload=UpdateVirtualKeyRequest(name="Renamed event key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.revoke_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        reason="Credential exposed in app config",
        actor=actor,
        scope=scope,
        db=db_session,
    )
    before_failed_revoke = await db_session.scalar(
        select(func.count())
        .select_from(ActivityEvent)
        .where(ActivityEvent.virtual_key_id == created_key.id)
    )
    with pytest.raises(VirtualKeyAlreadyRevokedError):
        await keys_facade.revoke_virtual_key(
            project_id=project.id,
            key_id=created_key.id,
            reason="Second revoke should fail",
            actor=actor,
            scope=scope,
            db=db_session,
        )
    after_failed_revoke = await db_session.scalar(
        select(func.count())
        .select_from(ActivityEvent)
        .where(ActivityEvent.virtual_key_id == created_key.id)
    )
    activity_events = list(
        await db_session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.virtual_key_id == created_key.id)
            .order_by(ActivityEvent.created_at)
        )
    )
    audit_events = list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == created_key.id)
            .order_by(AuditEvent.created_at)
        )
    )
    event_payload = " ".join(str(event.metadata_) for event in activity_events + audit_events)

    assert before_failed_revoke == after_failed_revoke
    assert {event.action for event in activity_events} >= {
        "virtual_key.created",
        "virtual_key.updated",
        "virtual_key.revoked",
    }
    assert {event.entity_type for event in audit_events} == {"virtual_key"}
    assert all(event.org_id == scope.org_id for event in activity_events + audit_events)
    assert any(
        event.metadata_.get("changed_fields", {}).get("name", {}).get("to") == "Renamed event key"
        for event in activity_events
    )
    assert any(
        event.metadata_.get("reason") == "Credential exposed in app config"
        for event in activity_events
    )
    assert created_key.key not in event_payload
    assert "key_hash" not in event_payload


async def test_project_archive_and_reactivation_events_include_resource_ids(
    db_session: AsyncSession,
) -> None:
    actor, scope, team, project, *_ = await _create_project_pool_and_models(db_session)

    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    activity_events = list(
        await db_session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.project_id == project.id)
            .where(ActivityEvent.action.in_(["project.deactivated", "project.reactivated"]))
            .order_by(ActivityEvent.created_at)
        )
    )
    audit_events = list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == project.id)
            .where(AuditEvent.action.in_(["project.deactivated", "project.reactivated"]))
            .order_by(AuditEvent.created_at)
        )
    )

    assert [event.action for event in activity_events] == [
        "project.deactivated",
        "project.reactivated",
    ]
    assert [event.action for event in audit_events] == [
        "project.deactivated",
        "project.reactivated",
    ]
    assert {event.entity_type for event in audit_events} == {"project"}
    assert all(event.org_id == scope.org_id for event in activity_events + audit_events)
    assert all(event.metadata_["project_id"] == str(project.id) for event in activity_events)
    assert all(event.metadata_["team_id"] == str(team.id) for event in activity_events)


async def test_archive_and_revoke_impact_previews_are_scoped_and_diagnostic(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    active_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Impact key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=active_key.key, requested_model="fast"),
        db=db_session,
    )
    await _record_usage_for_resolved(resolved=resolved, db_session=db_session, cost_cents=123)
    await _record_usage_for_resolved(
        resolved=resolved,
        db_session=db_session,
        cost_cents=0,
        http_status=429,
        error_code="rate_limited",
    )

    archived_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Archived impact project"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=archived_project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    archived_key = await keys_facade.create_virtual_key(
        project_id=archived_project.id,
        payload=CreateVirtualKeyRequest(name="Archived project key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.update_project(
        project_id=archived_project.id,
        payload=UpdateProjectRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    (
        other_actor,
        other_scope,
        other_team,
        other_project,
        other_provider,
        other_pool,
        other_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=other_scope,
        team_id=other_team.id,
        project_id=other_project.id,
        provider_id=other_provider.id,
        pool_id=other_pool.id,
        model_ids=[other_model.id],
        db_session=db_session,
    )
    other_key = await keys_facade.create_virtual_key(
        project_id=other_project.id,
        payload=CreateVirtualKeyRequest(name="Other org key"),
        actor=other_actor,
        scope=other_scope,
        db=db_session,
    )
    other_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=other_key.key, requested_model="fast"),
        db=db_session,
    )
    await _record_usage_for_resolved(
        resolved=other_resolved,
        db_session=db_session,
        cost_cents=999,
    )

    team_impact = await keys_facade.get_team_archive_impact(
        team_id=team.id,
        scope=scope,
        db=db_session,
    )
    project_impact = await keys_facade.get_project_archive_impact(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )
    archived_project_impact = await keys_facade.get_project_archive_impact(
        project_id=archived_project.id,
        scope=scope,
        db=db_session,
    )
    key_impact = await keys_facade.get_virtual_key_revoke_impact(
        project_id=project.id,
        key_id=active_key.id,
        scope=scope,
        db=db_session,
    )
    archived_key_impact = await keys_facade.get_virtual_key_revoke_impact(
        project_id=archived_project.id,
        key_id=archived_key.id,
        scope=scope,
        db=db_session,
    )

    assert team_impact.active_project_count == 1
    assert team_impact.active_virtual_key_count == 1
    assert team_impact.recent_request_count == 2
    assert team_impact.recent_cost_cents == 123
    assert project_impact.active_virtual_key_count == 1
    assert project_impact.recent_request_count == 2
    assert project_impact.recent_cost_cents == 123
    assert project_impact.effective_access.is_usable is True
    assert archived_project_impact.active_virtual_key_count == 0
    assert key_impact.last_used_at is not None
    assert key_impact.recent_request_count == 2
    assert key_impact.recent_cost_cents == 123
    assert key_impact.effective_access.is_usable is True
    assert key_impact.already_unusable_reason is None
    assert archived_key_impact.effective_access.blocking_code == "project_archived"
    assert archived_key_impact.already_unusable_reason == "The project is archived."

    with pytest.raises(ProjectNotFoundError):
        await keys_facade.get_project_archive_impact(
            project_id=project.id,
            scope=other_scope,
            db=db_session,
        )
    usage = await usage_facade.get_virtual_key_usage_summary(
        virtual_key_id=active_key.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert usage.totals.last_request_at is not None
    assert usage.totals.requests == 2
    assert usage.recent_errors[0].error_code == "rate_limited"


async def test_virtual_key_inventory_is_paginated_filtered_and_scoped(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    first = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="First inventory key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    second = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Second inventory key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    first_page = await keys_facade.list_virtual_key_inventory(
        scope=scope,
        visible_team_ids=None,
        visible_project_ids=None,
        manageable_team_ids={team.id},
        manageable_project_ids=set(),
        can_manage_all=False,
        team_id=None,
        project_id=None,
        status="unused",
        search="inventory",
        usage="never",
        limit=1,
        offset=0,
        db=db_session,
    )
    second_page = await keys_facade.list_virtual_key_inventory(
        scope=scope,
        visible_team_ids=None,
        visible_project_ids=None,
        manageable_team_ids={team.id},
        manageable_project_ids=set(),
        can_manage_all=False,
        team_id=None,
        project_id=None,
        status="unused",
        search="inventory",
        usage="never",
        limit=1,
        offset=1,
        db=db_session,
    )
    hidden = await keys_facade.list_virtual_key_inventory(
        scope=scope,
        visible_team_ids=set(),
        visible_project_ids=set(),
        manageable_team_ids=set(),
        manageable_project_ids=set(),
        can_manage_all=False,
        team_id=None,
        project_id=None,
        status=None,
        search=None,
        usage=None,
        limit=25,
        offset=0,
        db=db_session,
    )

    assert first_page.total == 2
    assert [item.id for item in first_page.items] == [second.id]
    assert [item.id for item in second_page.items] == [first.id]
    assert first_page.items[0].can_manage is True
    assert "key_hash" not in first_page.items[0].model_dump()
    assert "key" not in first_page.items[0].model_dump()
    assert hidden.total == 0


async def test_virtual_key_inventory_derived_status_pagination_is_not_truncated(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    now = datetime.now(UTC)
    keys = [
        VirtualKey(
            org_id=scope.org_id,
            project_id=project.id,
            name=f"Bulk key {index:04d}",
            key_hash=f"{index:064x}",
            key_prefix=f"bulk-{index:04d}",
            created_by=actor.id,
            last_used_at=now,
            created_at=now + timedelta(microseconds=index),
            updated_at=now + timedelta(microseconds=index),
        )
        for index in range(1005)
    ]
    db_session.add_all(keys)
    await db_session.commit()

    query_count = 0

    def count_query(*_args) -> None:
        nonlocal query_count
        query_count += 1

    assert db_session.bind is not None
    event.listen(db_session.bind.sync_engine, "before_cursor_execute", count_query)
    try:
        page = await keys_facade.list_virtual_key_inventory(
            scope=scope,
            visible_team_ids=None,
            visible_project_ids=None,
            manageable_team_ids={team.id},
            manageable_project_ids=set(),
            can_manage_all=False,
            team_id=None,
            project_id=None,
            status="active",
            search="Bulk key",
            usage="used",
            limit=5,
            offset=1000,
            db=db_session,
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", count_query)

    assert page.total == 1005
    assert query_count <= 10
    assert len(page.items) == 5
    assert [item.name for item in page.items] == [
        f"Bulk key {index:04d}" for index in range(4, -1, -1)
    ]


async def test_effective_access_explains_routability_and_key_blockers(
    db_session: AsyncSession,
) -> None:
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
    no_policy = await keys_facade.get_project_effective_access(
        project_id=project.id, scope=scope, db=db_session
    )
    assert no_policy.is_usable is False
    assert no_policy.blocking_code == "no_effective_access_policy"

    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    pool_row = await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assert pool_row.is_active is False
    unroutable = await keys_facade.get_project_effective_access(
        project_id=project.id, scope=scope, db=db_session
    )
    assert unroutable.blocking_code == "no_routable_provider_model"
    assert unroutable.access_policy is not None
    with pytest.raises(ProjectAccessUnavailableError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Blocked unroutable key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    key_count = await db_session.scalar(
        select(func.count()).select_from(VirtualKey).where(VirtualKey.project_id == project.id)
    )
    assert key_count == 0
    await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    usable = await keys_facade.get_project_effective_access(
        project_id=project.id, scope=scope, db=db_session
    )
    assert usable.is_usable is True
    assert usable.routes[0].provider_model == "gpt-5.4-mini"
    assert usable.access_policy is not None
    assert usable.access_policy.source_scope == "project"
    assert usable.limit_policies[0].source_scope == "project"

    team.is_active = False
    await db_session.commit()
    team_blocked = await keys_facade.get_project_effective_access(
        project_id=project.id, scope=scope, db=db_session
    )
    assert team_blocked.blocking_code == "team_archived"
    team.is_active = True
    await db_session.commit()

    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_blocked = await keys_facade.get_project_effective_access(
        project_id=project.id, scope=scope, db=db_session
    )
    assert project_blocked.blocking_code == "project_archived"
    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Diagnostic key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.revoke_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        reason="Test blocker",
        actor=actor,
        scope=scope,
        db=db_session,
    )
    revoked = await keys_facade.get_virtual_key_effective_access(
        project_id=project.id,
        key_id=created_key.id,
        scope=scope,
        db=db_session,
    )
    assert revoked.is_usable is False
    assert revoked.blocking_code == "key_revoked"
    assert revoked.ownership.key_active is False


async def test_empty_credential_pool_route_is_not_routable(
    db_session: AsyncSession,
) -> None:
    actor, scope, _, project, provider, _, fast_model, _ = await _create_project_pool_and_models(
        db_session
    )
    empty_pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Empty pool"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name="Empty route access",
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=empty_pool.id,
                        model_offering_id=[fast_model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )


async def test_access_route_validation_blocks_inactive_provider_pool_and_model(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        _project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)

    await providers_facade.update_provider(
        provider_id=provider.id,
        payload=UpdateProviderRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name="Inactive provider access",
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_id=[fast_model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )
    await providers_facade.update_provider(
        provider_id=provider.id,
        payload=UpdateProviderRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name="Inactive pool access",
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_id=[fast_model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )
    await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await providers_facade.update_model_offering(
        provider_id=provider.id,
        model_offering_id=fast_model.id,
        payload=UpdateProviderModelOfferingRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name="Inactive model access",
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_id=[fast_model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )


async def test_policy_runtime_requires_access_before_key_creation(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        _provider,
        _pool,
        _fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)

    with pytest.raises(PolicyNotConfiguredError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Console key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    key_count = await db_session.scalar(
        select(func.count()).select_from(VirtualKey).where(VirtualKey.project_id == project.id)
    )
    assert key_count == 0


async def test_virtual_key_creation_is_blocked_when_secret_delivery_is_disabled(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    await settings_facade.update_organization_settings(
        payload=UpdateOrganizationSettingsRequest(allow_secret_copy=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(SecretDeliveryDisabledError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Undeliverable key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    key_count = await db_session.scalar(
        select(func.count()).select_from(VirtualKey).where(VirtualKey.project_id == project.id)
    )
    assert key_count == 0


async def test_virtual_key_route_returns_structured_secret_delivery_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        _provider,
        _pool,
        _fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)

    async def reject_creation(**_kwargs):
        raise SecretDeliveryDisabledError

    monkeypatch.setattr(keys_facade, "create_virtual_key", reject_creation)

    with pytest.raises(HTTPException) as exc:
        await create_virtual_key_route(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Undeliverable key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "secret_delivery_disabled",
        "message": (
            "Virtual key creation is disabled because plaintext secret delivery is turned off."
        ),
    }


async def test_virtual_key_status_precedence_is_backend_derived(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    unused = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Unused key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assert unused.status == "unused"
    assert unused.is_usable is True

    await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=unused.key, requested_model="fast"),
        db=db_session,
    )
    active = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=unused.id,
        scope=scope,
        db=db_session,
    )
    assert active.status == "active"
    await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    no_access = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=unused.id,
        scope=scope,
        db=db_session,
    )
    assert no_access.status == "no_effective_access"
    assert no_access.is_usable is False
    await providers_facade.update_credential_pool(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=UpdateCredentialPoolRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    expiring = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(
            name="Expiring key",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assert expiring.status == "expiring_soon"

    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    archived = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=unused.id,
        scope=scope,
        db=db_session,
    )
    assert archived.status == "project_archived"
    assert archived.is_usable is False
    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await keys_facade.revoke_virtual_key(
        project_id=project.id,
        key_id=expiring.id,
        reason="Testing precedence",
        actor=actor,
        scope=scope,
        db=db_session,
    )
    revoked = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=expiring.id,
        scope=scope,
        db=db_session,
    )
    assert revoked.status == "revoked"
    assert revoked.is_usable is False


async def test_archived_ownership_blocks_key_creation_and_runtime(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
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
        payload=CreateVirtualKeyRequest(name="Existing key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(ProjectInactiveError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Blocked key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    with pytest.raises(InvalidVirtualKeyError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
        )

    await keys_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    team.is_active = False
    await db_session.commit()

    with pytest.raises(TeamInactiveError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="Blocked by team"),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    with pytest.raises(InvalidVirtualKeyError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
        )

    team.is_active = True
    await db_session.commit()
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )
    key = await keys_facade.get_virtual_key(
        project_id=project.id,
        key_id=created_key.id,
        scope=scope,
        db=db_session,
    )

    assert resolved.virtual_key_id == created_key.id
    assert key.revoked_at is None


async def test_project_access_policy_is_capped_by_team_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
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

    assert [model.id for model in accessible_models] == ["fast"]
    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="gpt-5.5",
            ),
            db=db_session,
        )


async def test_same_project_access_policies_union_routes(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access_policies = []
    for model in (fast_model, large_model):
        access = await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name=f"Project access {model.provider_model_name}",
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_id=[model.id],
                        public_model_name=model.provider_model_name,
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )
        access_policies.append(access)
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )

    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Union key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    accessible_models = await keys_facade.list_project_accessible_models(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )

    assert {model.id for model in accessible_models} == {"gpt-5.4-mini", "gpt-5.5"}
    summary = await keys_facade.get_project_effective_access(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )
    assert {policy.id for policy in summary.access_policies} == {
        policy.policy_id for policy in access_policies
    }
    assert {route.access_policy_id for route in summary.routes} == {
        policy.policy_id for policy in access_policies
    }
    assert (
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.4-mini"),
            db=db_session,
        )
    ).provider_model == "gpt-5.4-mini"
    assert (
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )
    ).provider_model == "gpt-5.5"


async def test_public_model_name_resolves_to_route_candidate(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Logical access",
            public_models=[
                AccessPolicyPublicModelInput(
                    public_model_name="chat-large",
                    routing_mode="ordered_fallback",
                    fallback_on=["timeout", "provider_5xx"],
                    candidates=[
                        AccessPolicyRouteCandidateInput(
                            provider_id=provider.id,
                            credential_pool_id=pool.id,
                            model_offering_id=fast_model.id,
                            priority=10,
                        )
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Logical key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    accessible_models = await keys_facade.list_accessible_models(
        raw_key=created_key.key,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="chat-large"),
        db=db_session,
    )
    summary = await keys_facade.get_project_effective_access(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )

    assert [model.id for model in accessible_models] == ["chat-large"]
    assert resolved.public_model_name == "chat-large"
    assert resolved.routing_mode == "ordered_fallback"
    assert resolved.provider_model == fast_model.provider_model_name
    assert resolved.route_candidate_id is not None
    assert resolved.access_policy_route_id is None
    assert summary.routes[0].public_model_name == "chat-large"
    assert summary.routes[0].routing_mode == "ordered_fallback"
    assert summary.routes[0].route_candidate_id == resolved.route_candidate_id


async def test_resolve_access_plan_orders_candidates_and_handles_streaming_and_pin(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    fallback_provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Fallback OpenAI",
            base_url="https://fallback.example.test/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fallback_pool = await providers_facade.create_credential_pool(
        provider_id=fallback_provider.id,
        payload=CreateCredentialPoolRequest(name="Fallback production"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fallback_credential = await providers_facade.create_provider_credential(
        provider_id=fallback_provider.id,
        payload=CreateProviderCredentialRequest(name="Fallback", api_key="fallback-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=fallback_provider.id,
        pool_id=fallback_pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=fallback_credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fallback_model = await providers_facade.create_model_offering(
        provider_id=fallback_provider.id,
        payload=CreateProviderModelOfferingRequest(provider_model_name="fallback-chat"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Fallback access",
            public_models=[
                AccessPolicyPublicModelInput(
                    public_model_name="chat-large",
                    routing_mode="ordered_fallback",
                    candidates=[
                        AccessPolicyRouteCandidateInput(
                            provider_id=provider.id,
                            credential_pool_id=pool.id,
                            model_offering_id=fast_model.id,
                            priority=10,
                        ),
                        AccessPolicyRouteCandidateInput(
                            provider_id=fallback_provider.id,
                            credential_pool_id=fallback_pool.id,
                            model_offering_id=fallback_model.id,
                            priority=20,
                        ),
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    primary_limits = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Primary provider limit",
            rules=[
                LimitPolicyRuleInput(
                    name="Primary requests",
                    limit_type="requests",
                    limit_value=10,
                    provider_id=provider.id,
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    fallback_limits = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Fallback provider limit",
            rules=[
                LimitPolicyRuleInput(
                    name="Fallback requests",
                    limit_type="requests",
                    limit_value=10,
                    provider_id=fallback_provider.id,
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    for limit in (primary_limits, fallback_limits):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="limit",
                policy_id=limit.policy_id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Fallback key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    plan = await keys_facade.resolve_access_plan(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="chat-large"),
        db=db_session,
    )
    streaming_plan = await keys_facade.resolve_access_plan(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="chat-large",
            streaming=True,
        ),
        db=db_session,
    )
    pinned_plan = await keys_facade.resolve_access_plan(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="chat-large",
            provider_id=fallback_provider.id,
        ),
        db=db_session,
    )

    assert [attempt.provider_id for attempt in plan.attempts] == [
        provider.id,
        fallback_provider.id,
    ]
    assert [attempt.limit_policy_ids for attempt in plan.attempts] == [
        [primary_limits.id],
        [fallback_limits.id],
    ]
    assert [
        candidate.provider_id
        for candidate in (
            await keys_facade.list_accessible_models(
                raw_key=created_key.key,
                db=db_session,
            )
        )[0].candidates
    ] == [provider.id, fallback_provider.id]
    assert [attempt.provider_id for attempt in streaming_plan.attempts] == [provider.id]
    assert streaming_plan.fallback_disabled_reason == "streaming_fallback_phase_2"
    assert [attempt.provider_id for attempt in pinned_plan.attempts] == [fallback_provider.id]
    assert pinned_plan.provider_pinned is True
    assert pinned_plan.fallback_disabled_reason == "provider_pinned"
    explanation = await keys_facade.explain_access_plan_for_virtual_key(
        org_id=scope.org_id,
        payload=ResolveAccessPlanForVirtualKeyRequest(
            virtual_key_id=created_key.id,
            requested_model="chat-large",
            provider_id=fallback_provider.id,
        ),
        db=db_session,
    )
    assert explanation.plan is not None
    assert [
        (candidate.provider_id, candidate.selected, candidate.skipped_reason)
        for candidate in explanation.candidates
    ] == [
        (provider.id, False, "provider_pinned_mismatch"),
        (fallback_provider.id, True, None),
    ]
    resolved_streaming = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="chat-large",
            streaming=True,
        ),
        db=db_session,
    )
    assert resolved_streaming.fallback_disabled_reason == "streaming_fallback_phase_2"


async def test_policy_simulation_project_admin_is_target_scoped(
    db_session: AsyncSession,
) -> None:
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
    other_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Other Console", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    for item in (project, other_project):
        await _assign_access_and_limit(
            scope=scope,
            team_id=item.team_id,
            project_id=item.id,
            provider_id=provider.id,
            pool_id=pool.id,
            model_ids=[fast_model.id],
            db_session=db_session,
        )
    own_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Own project key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    other_key = await keys_facade.create_virtual_key(
        project_id=other_project.id,
        payload=CreateVirtualKeyRequest(name="Other project key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="project-admin@example.com",
        role="org_member",
        permissions=[],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=own_key.id),
            requested_model="missing",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
        actor=project_admin,
    )

    assert result.subject.team_id == team.id
    assert result.subject.project_id == project.id
    with pytest.raises(PolicyPermissionError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=other_key.id),
                requested_model="missing",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
            ),
            scope=scope,
            db=db_session,
            actor=project_admin,
        )


async def test_policy_simulation_team_admin_is_target_scoped(
    db_session: AsyncSession,
) -> None:
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
    other_team = Team(org_id=scope.org_id, name="Other Team", slug=f"other-{uuid4()}")
    db_session.add(other_team)
    await db_session.commit()
    other_project = await keys_facade.create_project(
        team_id=other_team.id,
        payload=CreateProjectRequest(name="Other Team Console", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    for item in (project, other_project):
        await _assign_access_and_limit(
            scope=scope,
            team_id=item.team_id,
            project_id=item.id,
            provider_id=provider.id,
            pool_id=pool.id,
            model_ids=[fast_model.id],
            db_session=db_session,
        )
    team_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Team key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    other_key = await keys_facade.create_virtual_key(
        project_id=other_project.id,
        payload=CreateVirtualKeyRequest(name="Other team key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    team_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="team-admin@example.com",
        role="org_member",
        permissions=[],
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=team_key.id),
            requested_model="missing",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
        actor=team_admin,
    )

    assert result.subject.team_id == team.id
    with pytest.raises(PolicyPermissionError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=other_key.id),
                requested_model="missing",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
            ),
            scope=scope,
            db=db_session,
            actor=team_admin,
        )


async def test_policy_simulation_expired_key_with_naive_datetime_is_not_found(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Naive expired key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    virtual_key = await db_session.get(VirtualKey, created_key.id)
    assert virtual_key is not None
    virtual_key.expires_at = (datetime.now(UTC) - timedelta(days=1)).replace(tzinfo=None)
    await db_session.flush()

    with pytest.raises(VirtualKeyNotFoundError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
            ),
            scope=scope,
            db=db_session,
        )


async def test_policy_simulation_guardrails_require_guardrail_visibility(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail visibility key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    policy_viewer = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="policy-viewer@example.com",
        role="org_member",
        permissions=["policies.view"],
    )

    await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="missing",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
        actor=policy_viewer,
    )
    with pytest.raises(PolicyPermissionError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="missing",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=True,
            ),
            scope=scope,
            db=db_session,
            actor=policy_viewer,
        )
    with pytest.raises(PolicyPermissionError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="missing",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
                drafts=[
                    {
                        "kind": "guardrail",
                        "operation": "add_policy",
                        "assignment": {"scope_type": "org"},
                        "guardrail_policy": {
                            "name": "Draft guardrail",
                            "rules": [{"rule_type": "prompt_contains", "values": ["secret"]}],
                        },
                    }
                ],
            ),
            scope=scope,
            db=db_session,
            actor=policy_viewer,
        )


async def test_policy_simulation_scoped_admins_cannot_simulate_org_draft_assignments(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Draft scope key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="draft-project-admin@example.com",
        role="org_member",
        permissions=[],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )
    team_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="draft-team-admin@example.com",
        role="org_member",
        permissions=[],
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )
    org_viewer = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="draft-org-viewer@example.com",
        role="org_member",
        permissions=["policies.view"],
    )
    draft = {
        "kind": "access",
        "operation": "add_policy",
        "assignment": {"scope_type": "org"},
        "access_policy": {
            "name": "Org draft access",
            "public_models": [
                {
                    "public_model_name": "fast",
                    "routing_mode": "single_route",
                    "candidates": [
                        {
                            "provider_id": str(provider.id),
                            "credential_pool_id": str(pool.id),
                            "model_offering_id": str(fast_model.id),
                        }
                    ],
                }
            ],
        },
    }

    for scoped_actor in (project_admin, team_admin):
        with pytest.raises(PolicyPermissionError):
            await policies_facade.simulate_active_policies(
                payload=PolicySimulationRequest(
                    target=PolicySimulationTarget(virtual_key_id=created_key.id),
                    requested_model="fast",
                    gateway_endpoint="chat_completions",
                    include_limits=False,
                    include_guardrails=False,
                    drafts=[draft],
                ),
                scope=scope,
                db=db_session,
                actor=scoped_actor,
            )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[draft],
        ),
        scope=scope,
        db=db_session,
        actor=org_viewer,
    )
    assert result.final_decision == "allow"


async def test_policy_simulation_guardrail_draft_scope_is_authorized(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail draft scope key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    team_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="guardrail-draft-team-admin@example.com",
        role="org_member",
        permissions=[],
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    with pytest.raises(PolicyPermissionError):
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
                drafts=[
                    {
                        "kind": "guardrail",
                        "operation": "add_policy",
                        "assignment": {"scope_type": "org"},
                        "guardrail_policy": {
                            "name": "Org guardrail draft",
                            "rules": [{"rule_type": "prompt_contains", "values": ["secret"]}],
                        },
                    }
                ],
            ),
            scope=scope,
            db=db_session,
            actor=team_admin,
        )


async def test_resolve_access_plan_for_virtual_key_is_read_only(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Read-only simulation access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Simulation key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    plan = await keys_facade.resolve_access_plan_for_virtual_key(
        org_id=scope.org_id,
        payload=ResolveAccessPlanForVirtualKeyRequest(
            virtual_key_id=created_key.id,
            requested_model="fast",
        ),
        db=db_session,
    )
    stored_key = await db_session.get(VirtualKey, created_key.id)

    assert plan.virtual_key_id == created_key.id
    assert plan.attempts[0].provider_id == provider.id
    assert stored_key is not None
    assert stored_key.last_used_at is None


async def test_active_policy_simulation_reports_selected_route(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Simulation selected route key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert result.public_model_name == "fast"
    assert [(attempt.selected, attempt.would_attempt) for attempt in result.route_attempts] == [
        (True, True)
    ]
    assert result.decisions[0].decision_type == "provider_routing"
    assert result.decisions[0].outcome == "selected"


async def test_active_policy_simulation_limit_denial_does_not_reserve(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Simulation limit key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
    )
    reservation_count = await db_session.scalar(select(func.count(LimitPolicyReservation.id)))

    assert result.final_decision == "deny"
    assert result.denied_stage == "limit_reservation"
    assert result.limit_results[0].would_deny is True
    assert result.limit_results[0].reason_code == "request_token_limit"
    assert reservation_count == 0


async def test_active_policy_simulation_guardrail_content_and_applicability(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    guardrail = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Simulation guardrail",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["secret"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Simulation guardrail key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    blocked = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "contains a secret"},
        ),
        scope=scope,
        db=db_session,
    )
    applicability_only = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
        ),
        scope=scope,
        db=db_session,
    )

    assert blocked.final_decision == "deny"
    assert blocked.denied_stage == "request_guardrail"
    assert blocked.guardrail_results[0].decision == "blocked"
    assert blocked.guardrail_results[0].matched_values == ["secret"]
    assert applicability_only.final_decision == "allow"
    assert applicability_only.guardrail_results[0].decision == "not_evaluated"
    assert {warning.code for warning in applicability_only.warnings} >= {
        "guardrail_content_not_provided",
        "response_guardrail_content_not_provided",
    }


async def test_policy_simulation_draft_validation_rejects_invalid_payloads(
    db_session: AsyncSession,
) -> None:
    provider_id = uuid4()
    pool_id = uuid4()
    model_id = uuid4()
    bad_access = PolicySimulationRequest(
        target=PolicySimulationTarget(virtual_key_id=uuid4()),
        requested_model="fast",
        gateway_endpoint="chat_completions",
        drafts=[
            {
                "kind": "access",
                "operation": "add_policy",
                "assignment": {"scope_type": "org"},
                "access_policy": {
                    "name": "Bad access draft",
                    "public_models": [
                        {
                            "public_model_name": "fast",
                            "routing_mode": "single_route",
                            "candidates": [
                                {
                                    "provider_id": str(provider_id),
                                    "credential_pool_id": str(pool_id),
                                    "model_offering_id": str(model_id),
                                },
                                {
                                    "provider_id": str(provider_id),
                                    "credential_pool_id": str(pool_id),
                                    "model_offering_id": str(model_id),
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    )
    bad_limit = PolicySimulationRequest(
        target=PolicySimulationTarget(virtual_key_id=uuid4()),
        requested_model="fast",
        gateway_endpoint="chat_completions",
        drafts=[
            {
                "kind": "limit",
                "operation": "add_policy",
                "assignment": {"scope_type": "org"},
                "limit_policy": {
                    "name": "Bad limit draft",
                    "rules": [
                        {
                            "name": "Bad matcher",
                            "limit_type": "requests",
                            "limit_value": 1,
                            "interval_unit": "day",
                            "matchers": [
                                {
                                    "dimension": "not_a_dimension",
                                    "operator": "eq",
                                    "value_json": "x",
                                }
                            ],
                        }
                    ],
                },
            }
        ],
    )
    bad_guardrail = PolicySimulationRequest(
        target=PolicySimulationTarget(virtual_key_id=uuid4()),
        requested_model="fast",
        gateway_endpoint="chat_completions",
        drafts=[
            {
                "kind": "guardrail",
                "operation": "add_policy",
                "assignment": {"scope_type": "org"},
                "guardrail_policy": {
                    "name": "Bad guardrail draft",
                    "rules": [
                        {
                            "rule_type": "prompt_contains",
                            "effect": "deny",
                            "values": ["secret"],
                            "matchers": [
                                {
                                    "dimension": "not_a_dimension",
                                    "operator": "eq",
                                    "value_json": "x",
                                }
                            ],
                        }
                    ],
                },
            }
        ],
    )

    with pytest.raises(PolicySimulationValidationError):
        validate_policy_simulation_drafts(bad_access.drafts)
    with pytest.raises(PolicySimulationValidationError):
        validate_policy_simulation_drafts(bad_limit.drafts)
    with pytest.raises(PolicySimulationValidationError):
        validate_policy_simulation_drafts(bad_guardrail.drafts)
    with pytest.raises(PolicyValidationError):
        await policies_facade.simulate_active_policies(
            payload=bad_limit,
            scope=Scope(org_id=uuid4()),
            db=db_session,
        )


async def test_policy_simulation_replace_policy_rejects_bogus_explicit_assignment_ids(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Bogus replacement key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    base = {
        "target": {"virtual_key_id": str(created_key.id)},
        "requested_model": "fast",
        "gateway_endpoint": "chat_completions",
        "include_limits": False,
        "include_guardrails": False,
    }
    drafts = [
        {
            "kind": "access",
            "operation": "replace_policy",
            "existing_policy_id": str(uuid4()),
            "assignment": {"scope_type": "project", "project_id": str(project.id)},
            "access_policy": {
                "name": "Bogus access replacement",
                "public_models": [
                    {
                        "public_model_name": "fast",
                        "routing_mode": "single_route",
                        "candidates": [
                            {
                                "provider_id": str(provider.id),
                                "credential_pool_id": str(pool.id),
                                "model_offering_id": str(fast_model.id),
                            }
                        ],
                    }
                ],
            },
        },
        {
            "kind": "limit",
            "operation": "replace_policy",
            "existing_policy_id": str(uuid4()),
            "assignment": {"scope_type": "project", "project_id": str(project.id)},
            "limit_policy": {
                "name": "Bogus limit replacement",
                "rules": [
                    {
                        "name": "Requests",
                        "limit_type": "requests",
                        "limit_value": 1,
                        "interval_unit": "day",
                    }
                ],
            },
        },
        {
            "kind": "guardrail",
            "operation": "replace_policy",
            "existing_policy_id": str(uuid4()),
            "assignment": {"scope_type": "project", "project_id": str(project.id)},
            "guardrail_policy": {
                "name": "Bogus guardrail replacement",
                "rules": [{"rule_type": "prompt_contains", "values": ["secret"]}],
            },
        },
    ]

    for draft in drafts:
        with pytest.raises(PolicyValidationError):
            await policies_facade.simulate_active_policies(
                payload=PolicySimulationRequest(**(base | {"drafts": [draft]})),
                scope=scope,
                db=db_session,
            )


async def test_policy_simulation_scoped_replacement_ids_do_not_oracle_or_add(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    own_access, _own_limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    other_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Replacement oracle other project", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    other_access, _other_limit = await _assign_access_and_limit(
        scope=scope,
        team_id=other_project.team_id,
        project_id=other_project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[large_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Replacement oracle key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_admin = AuthenticatedUser(
        id=uuid4(),
        org_id=scope.org_id,
        email="replacement-project-admin@example.com",
        role="org_member",
        permissions=[],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    async def replace(existing_policy_id) -> None:
        await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
                drafts=[
                    {
                        "kind": "access",
                        "operation": "replace_policy",
                        "existing_policy_id": str(existing_policy_id),
                        "assignment": {"scope_type": "project", "project_id": str(project.id)},
                        "access_policy": {
                            "name": "Unauthorized replacement",
                            "public_models": [
                                {
                                    "public_model_name": "fast",
                                    "routing_mode": "single_route",
                                    "candidates": [
                                        {
                                            "provider_id": str(provider.id),
                                            "credential_pool_id": str(pool.id),
                                            "model_offering_id": str(large_model.id),
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            ),
            scope=scope,
            db=db_session,
            actor=project_admin,
        )

    with pytest.raises(PolicyPermissionError):
        await replace(uuid4())
    with pytest.raises(PolicyPermissionError):
        await replace(other_access.id)

    allowed = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "replace_policy",
                    "existing_policy_id": str(own_access.id),
                    "access_policy": {
                        "name": "Authorized replacement",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
        actor=project_admin,
    )
    assert allowed.final_decision == "allow"


async def test_policy_simulation_access_draft_can_select_unsaved_route(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="draft-fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Draft access",
                        "public_models": [
                            {
                                "public_model_name": "draft-fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(fast_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    selected = next(attempt for attempt in result.route_attempts if attempt.selected)
    assert result.final_decision == "allow"
    assert result.public_model_name == "draft-fast"
    assert selected.access_policy_id is None
    assert selected.public_model_id is None
    assert selected.route_candidate_id is None
    assert selected.provider_id == provider.id
    assert selected.draft_ref == "draft[0]:access_policy.public_models[0].candidates[0]"
    selected_decision = next(
        decision
        for decision in result.decisions
        if decision.decision_type == "provider_routing" and decision.outcome == "selected"
    )
    assert selected_decision.draft_ref == selected.draft_ref


async def test_policy_simulation_access_draft_evaluates_saved_limits(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access draft saved limit key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="draft-fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Draft access saved limit",
                        "public_models": [
                            {
                                "public_model_name": "draft-fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(fast_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "deny"
    assert result.denied_stage == "limit_reservation"
    assert result.limit_results[0].draft_ref is None
    selected = next(attempt for attempt in result.route_attempts if attempt.selected)
    assert selected.access_policy_id is None


async def test_policy_simulation_access_add_draft_non_overlapping_child_scope_denies(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        scope_type="team",
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access draft non-overlap key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Non-overlap project draft",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "deny"
    assert result.denied_stage == "access_resolution"
    assert result.route_attempts == []
    assert not any(
        decision.decision_type == "provider_routing" and decision.outcome == "selected"
        for decision in result.decisions
    )


async def test_policy_simulation_access_add_draft_narrows_to_allowed_route(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Team access with two routes",
            public_models=[
                {
                    "public_model_name": "fast",
                    "routing_mode": "ordered_fallback",
                    "fallback_on": ["provider_5xx"],
                    "max_route_attempts": 2,
                    "candidates": [
                        {
                            "provider_id": provider.id,
                            "credential_pool_id": pool.id,
                            "model_offering_id": fast_model.id,
                            "priority": 1,
                            "weight": 1,
                        },
                        {
                            "provider_id": provider.id,
                            "credential_pool_id": pool.id,
                            "model_offering_id": large_model.id,
                            "priority": 2,
                            "weight": 1,
                        },
                    ],
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="team",
            team_id=team.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access draft overlap key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Project narrowing draft",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    selected_attempts = [attempt for attempt in result.route_attempts if attempt.selected]
    selected_decisions = [
        decision
        for decision in result.decisions
        if decision.decision_type == "provider_routing" and decision.outcome == "selected"
    ]
    assert result.final_decision == "allow"
    assert len(selected_attempts) == 1
    assert selected_attempts[0].provider_model == large_model.provider_model_name
    assert selected_attempts[0].draft_ref == "draft[0]:access_policy.public_models[0].candidates[0]"
    assert len(selected_decisions) == 1
    assert selected_decisions[0].draft_ref == selected_attempts[0].draft_ref


async def test_policy_simulation_lower_scope_saved_empty_access_fails_closed(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        scope_type="team",
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Fail closed simulation key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Inactive project access",
            public_models=[
                AccessPolicyPublicModelInput(
                    public_model_name="fast",
                    routing_mode="single_route",
                    is_active=False,
                    candidates=[
                        AccessPolicyRouteCandidateInput(
                            provider_id=provider.id,
                            credential_pool_id=pool.id,
                            model_offering_id=fast_model.id,
                        )
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=project_access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "deny"
    assert result.denied_stage == "access_resolution"
    assert result.route_attempts == []
    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
        )


async def test_policy_simulation_inactive_lower_scope_access_draft_fails_closed(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        scope_type="team",
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive draft access key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Inactive draft access",
                        "is_active": False,
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(fast_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "deny"
    assert result.denied_stage == "access_resolution"
    assert result.route_attempts == []


async def test_policy_simulation_access_draft_active_flags_are_skipped(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    access, _limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access active flags key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    for draft_policy in (
        {
            "name": "Inactive replacement",
            "is_active": False,
            "public_models": [
                {
                    "public_model_name": "fast",
                    "candidates": [
                        {
                            "provider_id": str(provider.id),
                            "credential_pool_id": str(pool.id),
                            "model_offering_id": str(fast_model.id),
                        }
                    ],
                }
            ],
        },
        {
            "name": "Inactive public model replacement",
            "public_models": [
                {
                    "public_model_name": "fast",
                    "is_active": False,
                    "candidates": [
                        {
                            "provider_id": str(provider.id),
                            "credential_pool_id": str(pool.id),
                            "model_offering_id": str(fast_model.id),
                        }
                    ],
                }
            ],
        },
        {
            "name": "Inactive candidate replacement",
            "public_models": [
                {
                    "public_model_name": "fast",
                    "candidates": [
                        {
                            "provider_id": str(provider.id),
                            "credential_pool_id": str(pool.id),
                            "model_offering_id": str(fast_model.id),
                            "is_active": False,
                        }
                    ],
                }
            ],
        },
    ):
        result = await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
                drafts=[
                    {
                        "kind": "access",
                        "operation": "replace_policy",
                        "existing_policy_id": str(access.id),
                        "access_policy": draft_policy,
                    }
                ],
            ),
            scope=scope,
            db=db_session,
        )
        assert result.final_decision == "deny"
        assert result.route_attempts == []


async def test_policy_simulation_same_scope_access_draft_ordering_matches_runtime(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Same scope ordering key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def selected_model(*, priority: int = 100, weight: int = 100) -> str | None:
        result = await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                include_guardrails=False,
                drafts=[
                    {
                        "kind": "access",
                        "operation": "add_policy",
                        "assignment": {"scope_type": "project", "project_id": str(project.id)},
                        "access_policy": {
                            "name": "Same scope draft",
                            "public_models": [
                                {
                                    "public_model_name": "fast",
                                    "candidates": [
                                        {
                                            "provider_id": str(provider.id),
                                            "credential_pool_id": str(pool.id),
                                            "model_offering_id": str(large_model.id),
                                            "priority": priority,
                                            "weight": weight,
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            ),
            scope=scope,
            db=db_session,
        )
        selected = next(attempt for attempt in result.route_attempts if attempt.selected)
        return selected.provider_model

    assert await selected_model() == fast_model.provider_model_name
    assert await selected_model(priority=1) == large_model.provider_model_name
    assert await selected_model(weight=101) == large_model.provider_model_name


async def test_policy_simulation_multiple_access_drafts_have_distinct_refs(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Distinct access refs key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Access draft one",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(fast_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                },
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Access draft two",
                        "public_models": [
                            {
                                "public_model_name": "other",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                },
            ],
        ),
        scope=scope,
        db=db_session,
    )

    draft_refs = [attempt.draft_ref for attempt in result.route_attempts if attempt.draft_ref]
    assert {
        "draft[0]:access_policy.public_models[0].candidates[0]",
        "draft[1]:access_policy.public_models[0].candidates[0]",
    } <= set(draft_refs)


async def test_policy_simulation_access_replace_draft_changes_selected_route(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access, _limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access replace draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "replace_policy",
                    "existing_policy_id": str(access.id),
                    "access_policy": {
                        "name": "Replacement access",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    selected = [attempt for attempt in result.route_attempts if attempt.selected]
    assert len(selected) == 1
    assert selected[-1].draft_ref == "draft[0]:access_policy.public_models[0].candidates[0]"
    assert selected[-1].provider_model == large_model.provider_model_name
    assert result.public_model_name == "fast"


async def test_policy_simulation_access_replace_without_assignment_requires_active_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    own_access, _limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    other_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Other replace project", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    other_access, _other_limit = await _assign_access_and_limit(
        scope=scope,
        team_id=other_project.team_id,
        project_id=other_project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[large_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Access off-target replace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "access",
                    "operation": "replace_policy",
                    "existing_policy_id": str(other_access.id),
                    "access_policy": {
                        "name": "Off-target replacement access",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(large_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    selected = next(attempt for attempt in result.route_attempts if attempt.selected)
    assert selected.access_policy_id == own_access.policy_id
    assert selected.draft_ref is None


async def test_policy_simulation_limit_draft_denies_without_reserving(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Limit draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Draft token cap",
                        "rules": [
                            {
                                "name": "Draft request cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )
    reservation_count = await db_session.scalar(select(func.count(LimitPolicyReservation.id)))

    draft_result = next(item for item in result.limit_results if item.draft_ref is not None)
    assert result.final_decision == "deny"
    assert draft_result.policy_id is None
    assert draft_result.rule_id is None
    assert draft_result.assignment_id is None
    assert draft_result.would_deny is True
    assert draft_result.draft_ref == "draft[0]:limit_policy.rules[0]"
    assert result.decisions[-1].draft_ref == draft_result.draft_ref
    assert {warning.code for warning in result.warnings} >= {"draft_limit_counter_starts_at_zero"}
    assert reservation_count == 0


async def test_policy_simulation_limit_draft_route_filters_must_match(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Limit draft filter key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Mismatched draft token cap",
                        "rules": [
                            {
                                "name": "Wrong model cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                                "model_offering_id": str(large_model.id),
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert all(item.draft_ref is None for item in result.limit_results)


async def test_policy_simulation_inactive_add_limit_draft_is_skipped(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive add limit draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Inactive draft limit",
                        "is_active": False,
                        "rules": [
                            {
                                "name": "Inactive policy cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert all(item.draft_ref is None for item in result.limit_results)
    assert not result.warnings


async def test_policy_simulation_multiple_limit_drafts_have_distinct_refs(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Distinct limit refs key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Draft one",
                        "rules": [
                            {
                                "name": "One",
                                "limit_type": "requests",
                                "limit_value": 100,
                                "interval_unit": "day",
                            }
                        ],
                    },
                },
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Draft two",
                        "rules": [
                            {
                                "name": "Two",
                                "limit_type": "requests",
                                "limit_value": 100,
                                "interval_unit": "day",
                            }
                        ],
                    },
                },
            ],
        ),
        scope=scope,
        db=db_session,
    )

    draft_refs = [item.draft_ref for item in result.limit_results if item.draft_ref]
    assert {"draft[0]:limit_policy.rules[0]", "draft[1]:limit_policy.rules[0]"} <= set(draft_refs)


async def test_policy_simulation_limit_replace_removes_saved_limit(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Limit replace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "replace_policy",
                    "existing_policy_id": str(limit.id),
                    "limit_policy": {
                        "name": "Replacement limit",
                        "rules": [
                            {
                                "name": "Replacement request cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 100,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    replacement = next(
        item for item in result.limit_results if item.draft_ref == "draft[0]:limit_policy.rules[0]"
    )
    assert replacement.policy_id == limit.id
    assert replacement.limit_value == 100


async def test_policy_simulation_inactive_limit_replacement_removes_saved_limit(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive limit replacement key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "replace_policy",
                    "existing_policy_id": str(limit.id),
                    "limit_policy": {
                        "name": "Inactive replacement limit",
                        "is_active": False,
                        "rules": [
                            {
                                "name": "Inactive replacement cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert all(item.policy_id != limit.id for item in result.limit_results)
    assert not result.warnings


async def test_policy_simulation_inactive_limit_replacement_rule_is_skipped(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive limit rule replacement key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "replace_policy",
                    "existing_policy_id": str(limit.id),
                    "limit_policy": {
                        "name": "Replacement limit with inactive rule",
                        "rules": [
                            {
                                "name": "Inactive replacement cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                                "is_active": False,
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert all(item.policy_id != limit.id for item in result.limit_results)
    assert not result.warnings


async def test_policy_simulation_limit_replace_preserves_multiple_assignment_ids(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Shared multi-assignment limit",
            rules=[
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=100,
                    interval_unit="day",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    org_assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type="org",
        ),
        scope=scope,
        db=db_session,
    )
    project_assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Multi-assignment limit replacement key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "replace_policy",
                    "existing_policy_id": str(limit.id),
                    "limit_policy": {
                        "name": "Replacement shared limit",
                        "rules": [
                            {
                                "name": "Requests",
                                "limit_type": "requests",
                                "limit_value": 100,
                                "interval_unit": "day",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    replacement_results = [
        item
        for item in result.limit_results
        if item.policy_id == limit.id and item.draft_ref == "draft[0]:limit_policy.rules[0]"
    ]
    assert {item.assignment_id for item in replacement_results} == {
        org_assignment.id,
        project_assignment.id,
    }


async def test_policy_simulation_limit_replacement_warning_depends_on_counter_identity(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Warning identity limit",
            rules=[
                LimitPolicyRuleInput(
                    name="Saved requests",
                    limit_type="requests",
                    limit_value=100,
                    interval_unit="day",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Limit warning identity key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def warning_codes_for(draft: dict) -> set[str]:
        result = await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_guardrails=False,
                drafts=[draft],
            ),
            scope=scope,
            db=db_session,
        )
        return {warning.code for warning in result.warnings}

    preserved_replacement = {
        "kind": "limit",
        "operation": "replace_policy",
        "existing_policy_id": str(limit.id),
        "limit_policy": {
            "name": "Preserved replacement",
            "rules": [
                {
                    "name": "Saved requests",
                    "limit_type": "requests",
                    "limit_value": 100,
                    "interval_unit": "day",
                }
            ],
        },
    }
    explicit_assignment = preserved_replacement | {
        "assignment": {"scope_type": "project", "project_id": str(project.id)}
    }
    unmatched_rule = {
        "kind": "limit",
        "operation": "replace_policy",
        "existing_policy_id": str(limit.id),
        "limit_policy": {
            "name": "Replacement with new rule",
            "rules": [
                {
                    "name": "Saved requests",
                    "limit_type": "requests",
                    "limit_value": 100,
                    "interval_unit": "day",
                },
                {
                    "name": "New requests",
                    "limit_type": "requests",
                    "limit_value": 100,
                    "interval_unit": "day",
                },
            ],
        },
    }
    add_policy = {
        "kind": "limit",
        "operation": "add_policy",
        "assignment": {"scope_type": "project", "project_id": str(project.id)},
        "limit_policy": {
            "name": "Added limit",
            "rules": [
                {
                    "name": "Added requests",
                    "limit_type": "requests",
                    "limit_value": 100,
                    "interval_unit": "day",
                }
            ],
        },
    }

    assert await warning_codes_for(preserved_replacement) == set()
    assert await warning_codes_for(explicit_assignment) == {
        "draft_limit_assignment_counter_starts_at_zero"
    }
    assert "draft_limit_counter_starts_at_zero" in await warning_codes_for(unmatched_rule)
    assert await warning_codes_for(add_policy) == {"draft_limit_counter_starts_at_zero"}


async def test_policy_simulation_limit_replace_without_assignment_requires_active_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    _access, own_limit = await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=100,
        db_session=db_session,
    )
    other_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Other limit replace project", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    _other_access, other_limit = await _assign_access_and_limit(
        scope=scope,
        team_id=other_project.team_id,
        project_id=other_project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Limit off-target replace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            include_guardrails=False,
            drafts=[
                {
                    "kind": "limit",
                    "operation": "replace_policy",
                    "existing_policy_id": str(other_limit.id),
                    "limit_policy": {
                        "name": "Off-target replacement limit",
                        "rules": [
                            {
                                "name": "Off-target request cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert any(item.policy_id == own_limit.id for item in result.limit_results)
    assert all(item.draft_ref is None for item in result.limit_results)


async def test_policy_simulation_guardrail_draft_blocks_without_events(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "contains a draft secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {
                        "scope_type": "project",
                        "project_id": str(project.id),
                        "guardrail_assignment_mode": "enforce",
                    },
                    "guardrail_policy": {
                        "name": "Draft guardrail",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["draft secret"],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )
    events = await guardrails_facade.list_events(scope=scope, db=db_session)

    draft_result = next(item for item in result.guardrail_results if item.draft_ref is not None)
    assert result.final_decision == "deny"
    assert result.denied_stage == "request_guardrail"
    assert draft_result.policy_id is None
    assert draft_result.rule_id is None
    assert draft_result.assignment_id is None
    assert draft_result.decision == "blocked"
    assert draft_result.draft_ref == "draft[0]:guardrail_policy.rules[0]"
    assert result.decisions[-1].draft_ref == draft_result.draft_ref
    assert events == []


async def test_policy_simulation_inactive_guardrail_add_drafts_are_skipped(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive guardrail drafts key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    for guardrail_policy in (
        {
            "name": "Inactive guardrail draft policy",
            "is_active": False,
            "rules": [{"rule_type": "prompt_contains", "effect": "deny", "values": ["secret"]}],
        },
        {
            "name": "Inactive guardrail draft rule",
            "rules": [
                {
                    "rule_type": "prompt_contains",
                    "effect": "deny",
                    "values": ["secret"],
                    "is_active": False,
                }
            ],
        },
    ):
        result = await policies_facade.simulate_active_policies(
            payload=PolicySimulationRequest(
                target=PolicySimulationTarget(virtual_key_id=created_key.id),
                requested_model="fast",
                gateway_endpoint="chat_completions",
                include_limits=False,
                guardrail_input={"prompt_text": "secret"},
                drafts=[
                    {
                        "kind": "guardrail",
                        "operation": "add_policy",
                        "assignment": {"scope_type": "project", "project_id": str(project.id)},
                        "guardrail_policy": guardrail_policy,
                    }
                ],
            ),
            scope=scope,
            db=db_session,
        )
        assert result.final_decision == "allow"
        assert result.guardrail_results == []


async def test_policy_simulation_multiple_guardrail_drafts_have_distinct_refs(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Distinct guardrail refs key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "alpha beta"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "guardrail_policy": {
                        "name": "Alpha guardrail",
                        "rules": [{"rule_type": "prompt_contains", "values": ["alpha"]}],
                    },
                },
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "guardrail_policy": {
                        "name": "Beta guardrail",
                        "rules": [{"rule_type": "prompt_contains", "values": ["beta"]}],
                    },
                },
            ],
        ),
        scope=scope,
        db=db_session,
    )

    draft_refs = [item.draft_ref for item in result.guardrail_results if item.draft_ref]
    assert {
        "draft[0]:guardrail_policy.rules[0]",
        "draft[1]:guardrail_policy.rules[0]",
    } <= set(draft_refs)


async def test_policy_simulation_guardrail_replace_removes_saved_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    guardrail = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Saved guardrail",
            rules=[
                GuardrailRuleInput(rule_type="prompt_contains", effect="deny", values=["secret"])
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail replace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "contains a secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "replace_policy",
                    "existing_policy_id": str(guardrail.id),
                    "guardrail_policy": {
                        "name": "Replacement guardrail",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["other"],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert all(item.policy_id != guardrail.id for item in result.guardrail_results)
    assert any(
        item.draft_ref == "draft[0]:guardrail_policy.rules[0]" for item in result.guardrail_results
    )


async def test_policy_simulation_inactive_guardrail_replacement_removes_saved_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    guardrail = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Saved active guardrail",
            rules=[
                GuardrailRuleInput(rule_type="prompt_contains", effect="deny", values=["secret"])
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Inactive guardrail replacement key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "replace_policy",
                    "existing_policy_id": str(guardrail.id),
                    "guardrail_policy": {
                        "name": "Inactive replacement guardrail",
                        "is_active": False,
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["secret"],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert result.guardrail_results == []


async def test_policy_simulation_guardrail_replace_without_assignment_requires_active_policy(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    other_project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Other guardrail replace project", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    guardrail = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Off-target saved guardrail",
            rules=[
                GuardrailRuleInput(rule_type="prompt_contains", effect="deny", values=["secret"])
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail.id,
            scope_type="project",
            project_id=other_project.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail off-target replace key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "contains replacement secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "replace_policy",
                    "existing_policy_id": str(guardrail.id),
                    "guardrail_policy": {
                        "name": "Off-target replacement guardrail",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["replacement secret"],
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.final_decision == "allow"
    assert result.guardrail_results == []


async def test_policy_simulation_guardrail_draft_priority_interleaves_with_saved(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    guardrail = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Low priority saved guardrail",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["saved secret"],
                    priority=100,
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Guardrail priority key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "draft secret and saved secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "guardrail_policy": {
                        "name": "High priority draft guardrail",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["draft secret"],
                                "priority": 1,
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    first_block = next(item for item in result.guardrail_results if item.decision == "blocked")
    assert first_block.draft_ref == "draft[0]:guardrail_policy.rules[0]"
    first_guardrail_decision = next(
        decision for decision in result.decisions if decision.decision_type == "guardrail"
    )
    assert first_guardrail_decision.draft_ref == "draft[0]:guardrail_policy.rules[0]"

    tie_result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            include_limits=False,
            guardrail_input={"prompt_text": "draft secret and saved secret"},
            drafts=[
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "guardrail_policy": {
                        "name": "Same priority draft guardrail",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["draft secret"],
                                "priority": 100,
                            }
                        ],
                    },
                }
            ],
        ),
        scope=scope,
        db=db_session,
    )

    first_tie_block = next(
        item for item in tie_result.guardrail_results if item.decision == "blocked"
    )
    assert first_tie_block.policy_id == guardrail.id
    assert first_tie_block.draft_ref is None
    first_tie_decision = next(
        decision for decision in tie_result.decisions if decision.decision_type == "guardrail"
    )
    assert first_tie_decision.policy_id == guardrail.id
    assert first_tie_decision.draft_ref is None


async def test_policy_simulation_with_drafts_writes_no_side_effect_rows(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="No side effects draft key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    before = await _draft_side_effect_counts(db_session)

    result = await policies_facade.simulate_active_policies(
        payload=PolicySimulationRequest(
            target=PolicySimulationTarget(virtual_key_id=created_key.id),
            requested_model="fast",
            gateway_endpoint="chat_completions",
            estimated_input_tokens=2,
            guardrail_input={"prompt_text": "contains a draft secret"},
            drafts=[
                {
                    "kind": "access",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "access_policy": {
                        "name": "Draft access no side effects",
                        "public_models": [
                            {
                                "public_model_name": "fast",
                                "routing_mode": "single_route",
                                "candidates": [
                                    {
                                        "provider_id": str(provider.id),
                                        "credential_pool_id": str(pool.id),
                                        "model_offering_id": str(fast_model.id),
                                    }
                                ],
                            }
                        ],
                    },
                },
                {
                    "kind": "limit",
                    "operation": "add_policy",
                    "assignment": {"scope_type": "project", "project_id": str(project.id)},
                    "limit_policy": {
                        "name": "Draft limit no side effects",
                        "rules": [
                            {
                                "name": "Draft request cap",
                                "limit_type": "tokens_per_request",
                                "limit_value": 1,
                                "interval_unit": "lifetime",
                            }
                        ],
                    },
                },
                {
                    "kind": "guardrail",
                    "operation": "add_policy",
                    "assignment": {
                        "scope_type": "project",
                        "project_id": str(project.id),
                        "guardrail_assignment_mode": "enforce",
                    },
                    "guardrail_policy": {
                        "name": "Draft guardrail no side effects",
                        "rules": [
                            {
                                "rule_type": "prompt_contains",
                                "effect": "deny",
                                "values": ["draft secret"],
                            }
                        ],
                    },
                },
            ],
        ),
        scope=scope,
        db=db_session,
    )
    after = await _draft_side_effect_counts(db_session)

    assert result.final_decision == "deny"
    assert any(attempt.draft_ref for attempt in result.route_attempts)
    assert any(item.draft_ref for item in result.limit_results)
    assert any(item.draft_ref for item in result.guardrail_results)
    assert after == before


async def test_runtime_limit_evaluator_reports_denial_without_reserving(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    await _assign_access_and_limit(
        scope=scope,
        team_id=project.team_id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=1,
        db_session=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Evaluator key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )

    evaluation = await evaluate_runtime_limits_readonly(
        payload=RuntimeLimitEvaluationInput(
            resolved=resolved,
            estimated_input_tokens=2,
            requested_output_tokens=None,
            estimated_cost_cents=0,
            estimated_cost_micro_cents=0,
            limit_types={"tokens_per_request"},
        ),
        db=db_session,
    )

    assert evaluation.denial is not None
    assert evaluation.denial.reason_code == "request_token_limit"
    assert evaluation.denial.current_usage == 2
    assert evaluation.denial.active_reserved_usage == 0
    assert evaluation.denial.attempted_usage == 2


async def test_resolve_access_plan_filters_candidates_by_gateway_endpoint(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _large_model,
    ) = await _create_project_pool_and_models(db_session)
    provider_row = await db_session.get(Provider, provider.id)
    assert provider_row is not None
    provider_row.supported_integration = "anthropic_messages"
    await db_session.commit()
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Anthropic-only access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="chat-large",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Endpoint key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access_plan(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="chat-large",
                gateway_endpoint="chat_completions",
            ),
            db=db_session,
        )
    anthropic_plan = await keys_facade.resolve_access_plan(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="chat-large",
            gateway_endpoint="anthropic_messages",
        ),
        db=db_session,
    )
    assert [attempt.provider_id for attempt in anthropic_plan.attempts] == [provider.id]


async def test_access_narrows_through_org_team_project_and_virtual_key(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    org_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Org access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                ),
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[large_model.id],
                    public_model_name="gpt-5.5",
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )
    team_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Team access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    project_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Project tries to broaden",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                ),
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[large_model.id],
                    public_model_name="gpt-5.5",
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )
    key_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Key access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    for payload in (
        CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=org_access.policy_id,
            scope_type="org",
        ),
        CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=team_access.policy_id,
            scope_type="team",
            team_id=team.id,
        ),
        CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=project_access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
    ):
        await policies_facade.create_policy_assignment(payload=payload, scope=scope, db=db_session)

    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Narrowed key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=key_access.policy_id,
            scope_type="virtual_key",
            virtual_key_id=created_key.id,
        ),
        scope=scope,
        db=db_session,
    )

    key_models = await keys_facade.list_accessible_models(raw_key=created_key.key, db=db_session)
    key_options = await policies_facade.get_access_policy_options(
        scope_type="virtual_key",
        team_id=None,
        project_id=None,
        virtual_key_id=created_key.id,
        exclude_policy_id=None,
        scope=scope,
        db=db_session,
    )

    assert [model.id for model in key_models] == ["fast"]
    assert key_models[0].provider_name == provider.name
    assert key_models[0].pool_name == pool.name
    assert key_models[0].access_policy_name == key_access.name
    assert key_models[0].source_scope == "virtual_key"
    assert [
        model.provider_model_name
        for provider_option in key_options.providers
        for pool_option in provider_option.pools
        for model in pool_option.models
    ] == ["gpt-5.4-mini"]
    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )


async def test_multiple_parent_and_child_policies_do_not_broaden_access(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    for name, model, scope_type, target in (
        ("Org fast", fast_model, "org", {}),
        ("Org large", large_model, "org", {}),
        ("Team fast", fast_model, "team", {"team_id": team.id}),
        ("Project large only", large_model, "project", {"project_id": project.id}),
    ):
        access = await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name=name,
                public_models=[
                    _public_model_route(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_id=[model.id],
                        public_model_name=model.provider_model_name,
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type=scope_type,
                **target,
            ),
            scope=scope,
            db=db_session,
        )

    accessible_models = await keys_facade.list_project_accessible_models(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )

    assert accessible_models == []
    with pytest.raises(ProjectAccessUnavailableError):
        await keys_facade.create_virtual_key(
            project_id=project.id,
            payload=CreateVirtualKeyRequest(name="No broadening key"),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_policy_assignment_validates_targets_and_rejects_duplicate_active_assignment(
    db_session: AsyncSession,
) -> None:
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
    (
        _other_actor,
        _other_scope,
        other_team,
        other_project,
        *_,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Scoped access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )

    assert assignment.project_id == project.id
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Scoped key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyAssignmentConflictError):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type="project",
                team_id=other_team.id,
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type="virtual_key",
                project_id=other_project.id,
                virtual_key_id=created_key.id,
            ),
            scope=scope,
            db=db_session,
        )
    with pytest.raises(PolicyNotFoundError):
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="access",
                policy_id=access.policy_id,
                scope_type="team",
                team_id=other_team.id,
            ),
            scope=scope,
            db=db_session,
        )


async def test_policy_assignment_can_target_shared_policy_id(
    db_session: AsyncSession,
) -> None:
    (
        _actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Shared id access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_id=access.policy_id,
            policy_type="access",
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )

    assert access.policy_id is not None
    assert assignment.policy_id == access.policy_id
    assert "access_policy_id" not in assignment.model_dump()
    assert "limit_policy_id" not in assignment.model_dump()
    assert assignment.scope_target_key == f"project:{project.id}"


async def test_delete_access_policy_closes_assignments_and_preserves_trace_fk(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        _team,
        project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Trace preserved access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                )
            ],
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_id=access.policy_id,
            policy_type="access",
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    gateway_request_id = await usage_facade.create_gateway_request(
        payload=CreateGatewayRequest(
            org_id=scope.org_id,
            team_id=project.team_id,
            project_id=project.id,
            gateway_endpoint="chat_completions",
            requested_model="fast",
        ),
        db=db_session,
    )
    decision_id = await usage_facade.create_gateway_policy_decision(
        values={
            "org_id": scope.org_id,
            "gateway_request_id": gateway_request_id,
            "decision_type": "access",
            "stage": "access_resolution",
            "outcome": "allowed",
            "enforced": True,
            "policy_id": access.policy_id,
            "assignment_id": assignment.id,
            "dimension_snapshot": {},
            "metadata_": {},
        },
        db=db_session,
    )

    await policies_facade.delete_access_policy(
        policy_id=access.id,
        scope=scope,
        db=db_session,
        actor=actor,
    )

    stored_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    active_assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=scope.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=None,
        policy_type="access",
        db=db_session,
    )
    stored_decision = await db_session.get(GatewayPolicyDecision, decision_id)

    assert stored_assignment is not None
    assert stored_assignment.is_active is False
    assert stored_assignment.effective_to is not None
    assert all(item.id != assignment.id for item in active_assignments)
    assert stored_decision is not None
    assert stored_decision.assignment_id == assignment.id


async def test_delete_limit_policy_closes_assignments_without_deleting_history(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team, project, *_ = await _create_project_pool_and_models(db_session)
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(name="Historical limit"),
        scope=scope,
        db=db_session,
        actor=actor,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_id=limit.policy_id,
            policy_type="limit",
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
        actor=actor,
    )

    await policies_facade.delete_limit_policy(
        policy_id=limit.id,
        scope=scope,
        db=db_session,
        actor=actor,
    )

    stored_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    active_assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=scope.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=None,
        policy_type="limit",
        db=db_session,
    )

    assert stored_assignment is not None
    assert stored_assignment.is_active is False
    assert stored_assignment.effective_to is not None
    assert all(item.id != assignment.id for item in active_assignments)


async def test_limit_policy_request_limit_is_enforced(db_session: AsyncSession) -> None:
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

    with pytest.raises(gateway_limits.GatewayLimitDeniedError) as exc:
        await gateway_limits.enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=1,
            requested_output_tokens=1,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request token limit exceeded"


async def test_limit_policy_runtime_skips_unmatched_rule_matchers(
    db_session: AsyncSession,
) -> None:
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
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_requests=1,
        db_session=db_session,
    )
    await policies_facade.update_limit_policy_rule(
        rule_id=limit.rules[0].id,
        payload=UpdateLimitPolicyRuleRequest(
            matchers=[
                LimitPolicyRuleMatcherInput(
                    dimension="public_model_name",
                    operator="eq",
                    value_json="slow",
                )
            ]
        ),
        scope=scope,
        db=db_session,
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

    reservation_ids = await gateway_limits.enforce_limit_policies(
        resolved=resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )

    reservation_count = await db_session.scalar(
        select(func.count()).select_from(LimitPolicyReservation)
    )
    assert reservation_ids == []
    assert reservation_count == 0


async def test_limit_policy_runtime_enforces_matching_rule_matchers(
    db_session: AsyncSession,
) -> None:
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
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_requests=1,
        db_session=db_session,
    )
    await policies_facade.update_limit_policy_rule(
        rule_id=limit.rules[0].id,
        payload=UpdateLimitPolicyRuleRequest(
            matchers=[
                LimitPolicyRuleMatcherInput(
                    dimension="public_model_name",
                    operator="eq",
                    value_json="fast",
                )
            ]
        ),
        scope=scope,
        db=db_session,
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
    await _record_usage_for_resolved(resolved=resolved, db_session=db_session)

    with pytest.raises(gateway_limits.GatewayLimitDeniedError) as exc:
        await gateway_limits.enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"


async def test_limit_policy_runtime_active_reservations_are_partitioned(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Partitioned access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                ),
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=large_model.id,
                    public_model_name="slow",
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Partitioned request caps",
            rules=[
                LimitPolicyRuleInput(
                    name="One active request per public model",
                    limit_type="requests",
                    limit_value=1,
                    interval_unit="day",
                    partitions=[
                        LimitPolicyRulePartitionInput(
                            dimension="public_model_name",
                            position=0,
                        )
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fast_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )
    slow_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="slow"),
        db=db_session,
    )

    await gateway_limits.enforce_limit_policies(
        resolved=fast_resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )
    await gateway_limits.enforce_limit_policies(
        resolved=slow_resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )

    reservations = (
        await db_session.scalars(
            select(LimitPolicyReservation).order_by(LimitPolicyReservation.created_at)
        )
    ).all()
    assert [reservation.counter_key for reservation in reservations] == [
        "public_model_name=fast",
        "public_model_name=slow",
    ]
    assert all(
        reservation.window_descriptor.startswith("day:1:")
        for reservation in reservations
        if reservation.window_descriptor is not None
    )
    assert [reservation.counting_unit for reservation in reservations] == [
        "logical_request",
        "logical_request",
    ]
    assert [
        reservation.dimension_snapshot["public_model_name"] for reservation in reservations
    ] == [
        "fast",
        "slow",
    ]
    with pytest.raises(gateway_limits.GatewayLimitDeniedError) as exc:
        await gateway_limits.enforce_limit_policies(
            resolved=fast_resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"


async def test_limit_policy_runtime_locks_resolved_counter_identity(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_requests=1,
        db_session=db_session,
    )
    updated_rule = await policies_facade.update_limit_policy_rule(
        rule_id=limit.rules[0].id,
        payload=UpdateLimitPolicyRuleRequest(
            partitions=[
                LimitPolicyRulePartitionInput(
                    dimension="public_model_name",
                    position=0,
                )
            ]
        ),
        scope=scope,
        db=db_session,
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
    lock_identities: list[str] = []

    async def capture_counter_lock(*, identity: str, db: AsyncSession) -> None:
        lock_identities.append(identity)

    monkeypatch.setattr(usage_facade, "acquire_limit_counter_lock", capture_counter_lock)

    await gateway_limits.enforce_limit_policies(
        resolved=resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )

    assert len(lock_identities) == 1
    assert str(limit.id) in lock_identities[0]
    assert str(updated_rule.id) in lock_identities[0]
    assert "logical_request" in lock_identities[0]
    assert "public_model_name=fast" in lock_identities[0]


async def test_limit_policy_runtime_attempt_scoped_dimensions_use_route_attempt_unit(
    db_session: AsyncSession,
) -> None:
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
    _access, limit = await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_requests=1,
        db_session=db_session,
    )
    await policies_facade.update_limit_policy_rule(
        rule_id=limit.rules[0].id,
        payload=UpdateLimitPolicyRuleRequest(
            partitions=[
                LimitPolicyRulePartitionInput(
                    dimension="provider_id",
                    position=0,
                )
            ]
        ),
        scope=scope,
        db=db_session,
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

    await gateway_limits.enforce_limit_policies(
        resolved=resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )
    await gateway_accounting.record_proxy_request(
        resolved=resolved,
        http_status=200,
        latency_ms=10,
        usage=unknown_usage(),
        error_code=None,
        gateway_endpoint="chat_completions",
        db=db_session,
    )

    reservation = await db_session.scalar(select(LimitPolicyReservation))
    usage_record = await db_session.scalar(select(UsageRecord))
    assert reservation is not None
    assert usage_record is not None
    assert reservation.counting_unit == "route_attempt"
    assert usage_record.limit_counting_unit == "route_attempt"
    assert reservation.counter_key == f"provider_id={resolved.provider_id}"
    assert usage_record.limit_counter_key == f"provider_id={resolved.provider_id}"
    assert reservation.window_descriptor is not None
    assert reservation.window_descriptor.startswith("day:1:")
    assert usage_record.limit_window_descriptor == reservation.window_descriptor


async def test_limit_policy_runtime_committed_usage_is_partitioned(
    db_session: AsyncSession,
) -> None:
    (
        actor,
        scope,
        team,
        project,
        provider,
        pool,
        fast_model,
        large_model,
    ) = await _create_project_pool_and_models(db_session)
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Committed partition access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                    public_model_name="fast",
                ),
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=large_model.id,
                    public_model_name="slow",
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Committed partition caps",
            rules=[
                LimitPolicyRuleInput(
                    name="One committed request per public model",
                    limit_type="requests",
                    limit_value=1,
                    interval_unit="day",
                    partitions=[
                        LimitPolicyRulePartitionInput(
                            dimension="public_model_name",
                            position=0,
                        )
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="limit",
            policy_id=limit.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fast_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
        db=db_session,
    )
    slow_resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="slow"),
        db=db_session,
    )
    await gateway_accounting.record_proxy_request(
        resolved=fast_resolved,
        http_status=200,
        latency_ms=10,
        usage=unknown_usage(),
        error_code=None,
        gateway_endpoint="chat_completions",
        db=db_session,
    )

    await gateway_limits.enforce_limit_policies(
        resolved=slow_resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )

    with pytest.raises(gateway_limits.GatewayLimitDeniedError) as exc:
        await gateway_limits.enforce_limit_policies(
            resolved=fast_resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"


async def test_tokens_per_request_limit_does_not_create_reservation(
    db_session: AsyncSession,
) -> None:
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
    await _assign_access_and_limit(
        scope=scope,
        team_id=team.id,
        project_id=project.id,
        provider_id=provider.id,
        pool_id=pool.id,
        model_ids=[fast_model.id],
        max_tokens_per_request=10,
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

    reservation_ids = await gateway_limits.enforce_limit_policies(
        resolved=resolved,
        estimated_input_tokens=1,
        requested_output_tokens=1,
        db=db_session,
    )

    reservation_count = await db_session.scalar(
        select(func.count()).select_from(LimitPolicyReservation)
    )
    assert reservation_ids == []
    assert reservation_count == 0


async def test_tokens_per_request_limit_requires_lifetime_window(
    db_session: AsyncSession,
) -> None:
    _actor, scope, *_ = await _create_project_pool_and_models(db_session)

    with pytest.raises(PolicyValidationError):
        await policies_facade.create_limit_policy(
            payload=CreateLimitPolicyRequest(
                name="Invalid request token cap",
                rules=[
                    LimitPolicyRuleInput(
                        name="Request token cap",
                        limit_type="tokens_per_request",
                        limit_value=10,
                        interval_unit="day",
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )

    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(name="Request token caps"),
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_limit_policy_rule(
            policy_id=policy.id,
            payload=CreateLimitPolicyRuleRequest(
                name="Invalid rule",
                limit_type="tokens_per_request",
                limit_value=10,
                interval_unit="day",
            ),
            scope=scope,
            db=db_session,
        )
    rule = await policies_facade.create_limit_policy_rule(
        policy_id=policy.id,
        payload=CreateLimitPolicyRuleRequest(
            name="Valid rule",
            limit_type="tokens_per_request",
            limit_value=10,
            interval_unit="lifetime",
        ),
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.update_limit_policy_rule(
            rule_id=rule.id,
            payload=UpdateLimitPolicyRuleRequest(interval_unit="day"),
            scope=scope,
            db=db_session,
        )


async def test_limit_policy_rule_matchers_round_trip_through_service(
    db_session: AsyncSession,
) -> None:
    _actor, scope, *_ = await _create_project_pool_and_models(db_session)

    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Partitioned request limits",
            rules=[
                LimitPolicyRuleInput(
                    name="Per model per project",
                    limit_type="requests",
                    limit_value=100,
                    interval_unit="day",
                    matchers=[
                        LimitPolicyRuleMatcherInput(
                            dimension="public_model_name",
                            operator="eq",
                            value_json="fast-general",
                        )
                    ],
                    partitions=[
                        LimitPolicyRulePartitionInput(dimension="project_id", position=0),
                        LimitPolicyRulePartitionInput(
                            dimension="public_model_name",
                            position=1,
                        ),
                    ],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )

    rule = policy.rules[0]
    assert [
        (matcher.dimension, matcher.operator, matcher.value_json) for matcher in rule.matchers
    ] == [("public_model_name", "eq", "fast-general")]
    assert [(partition.dimension, partition.position) for partition in rule.partitions] == [
        ("project_id", 0),
        ("public_model_name", 1),
    ]

    updated = await policies_facade.update_limit_policy_rule(
        rule_id=rule.id,
        payload=UpdateLimitPolicyRuleRequest(
            matchers=[
                LimitPolicyRuleMatcherInput(
                    dimension="streaming",
                    operator="exists",
                )
            ],
            partitions=[],
        ),
        scope=scope,
        db=db_session,
    )

    assert [
        (matcher.dimension, matcher.operator, matcher.value_json) for matcher in updated.matchers
    ] == [("streaming", "exists", None)]
    assert updated.partitions == []


async def test_limit_policy_rule_update_creates_new_revision(
    db_session: AsyncSession,
) -> None:
    (
        _actor,
        scope,
        *_,
    ) = await _create_project_pool_and_models(db_session)
    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Revisioned limits",
            rules=[
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=1,
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    original_rule = policy.rules[0]

    updated = await policies_facade.update_limit_policy_rule(
        rule_id=original_rule.id,
        payload=UpdateLimitPolicyRuleRequest(limit_value=2),
        scope=scope,
        db=db_session,
    )
    assert updated.id != original_rule.id

    legacy_rule = await policies_repository.get_limit_policy_rule(
        rule_id=original_rule.id,
        org_id=scope.org_id,
        db=db_session,
    )
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db_session,
    )
    assert legacy_rule is not None
    assert active_revision is not None
    assert legacy_rule.limit_value == 1
    assert legacy_rule.policy_revision_id != active_revision.id
    assert updated.limit_value == 2
    assert updated.policy_revision_id == active_revision.id


async def test_limit_policy_rule_update_targets_copied_rule_by_source_id(
    db_session: AsyncSession,
) -> None:
    _actor, scope, *_ = await _create_project_pool_and_models(db_session)
    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Duplicate rule limits",
            rules=[
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=100,
                    partitions=[LimitPolicyRulePartitionInput(dimension="project_id", position=0)],
                ),
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=100,
                    partitions=[
                        LimitPolicyRulePartitionInput(dimension="virtual_key_id", position=0)
                    ],
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )

    updated = await policies_facade.update_limit_policy_rule(
        rule_id=policy.rules[1].id,
        payload=UpdateLimitPolicyRuleRequest(limit_value=200),
        scope=scope,
        db=db_session,
    )
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db_session,
    )
    assert active_revision is not None
    active_rules = await policies_repository.list_limit_policy_revision_rules(
        org_id=scope.org_id,
        limit_policy_id=policy.id,
        policy_revision_id=active_revision.id,
        db=db_session,
    )
    value_by_partition: dict[str, int] = {}
    for rule in active_rules:
        partitions = await policies_repository.list_limit_policy_rule_partitions(
            org_id=scope.org_id,
            rule_id=rule.id,
            db=db_session,
        )
        value_by_partition[partitions[0].dimension] = rule.limit_value

    assert updated.limit_value == 200
    assert value_by_partition == {"project_id": 100, "virtual_key_id": 200}


async def test_limit_policy_rule_delete_targets_copied_rule_by_source_id(
    db_session: AsyncSession,
) -> None:
    _actor, scope, *_ = await _create_project_pool_and_models(db_session)
    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Duplicate rule delete limits",
            rules=[
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=100,
                    partitions=[LimitPolicyRulePartitionInput(dimension="project_id", position=0)],
                ),
                LimitPolicyRuleInput(
                    name="Requests",
                    limit_type="requests",
                    limit_value=100,
                    partitions=[
                        LimitPolicyRulePartitionInput(dimension="virtual_key_id", position=0)
                    ],
                ),
            ],
        ),
        scope=scope,
        db=db_session,
    )

    await policies_facade.delete_limit_policy_rule(
        rule_id=policy.rules[1].id,
        scope=scope,
        db=db_session,
    )
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db_session,
    )
    assert active_revision is not None
    active_rules = await policies_repository.list_limit_policy_revision_rules(
        org_id=scope.org_id,
        limit_policy_id=policy.id,
        policy_revision_id=active_revision.id,
        db=db_session,
    )
    remaining_partitions = []
    for rule in active_rules:
        partitions = await policies_repository.list_limit_policy_rule_partitions(
            org_id=scope.org_id,
            rule_id=rule.id,
            db=db_session,
        )
        remaining_partitions.append(partitions[0].dimension)

    assert remaining_partitions == ["project_id"]


async def test_limit_policy_legacy_filters_materialize_as_matchers(
    db_session: AsyncSession,
) -> None:
    (
        _actor,
        scope,
        _team,
        _project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)

    policy = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(
            name="Legacy filtered limits",
            rules=[
                LimitPolicyRuleInput(
                    name="Provider cap",
                    limit_type="requests",
                    limit_value=1,
                    interval_unit="day",
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=fast_model.id,
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert [
        (matcher.dimension, matcher.operator, matcher.value_json)
        for matcher in policy.rules[0].matchers
    ] == [
        ("provider_id", "eq", str(provider.id)),
        ("credential_pool_id", "eq", str(pool.id)),
        ("provider_model_offering_id", "eq", str(fast_model.id)),
    ]


async def test_limit_policy_rule_matcher_validation_uses_dimension_registry(
    db_session: AsyncSession,
) -> None:
    _actor, scope, *_ = await _create_project_pool_and_models(db_session)

    with pytest.raises(PolicyValidationError):
        await policies_facade.create_limit_policy(
            payload=CreateLimitPolicyRequest(
                name="Invalid dimensions",
                rules=[
                    LimitPolicyRuleInput(
                        name="Bad provider credential scope",
                        limit_type="requests",
                        limit_value=100,
                        interval_unit="day",
                        matchers=[
                            LimitPolicyRuleMatcherInput(
                                dimension="provider_credential_id",
                                operator="exists",
                            )
                        ],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )

    with pytest.raises(PolicyValidationError):
        await policies_facade.create_limit_policy(
            payload=CreateLimitPolicyRequest(
                name="Partitioned token cap",
                rules=[
                    LimitPolicyRuleInput(
                        name="Bad token cap",
                        limit_type="tokens_per_request",
                        limit_value=100,
                        interval_unit="lifetime",
                        partitions=[
                            LimitPolicyRulePartitionInput(dimension="project_id", position=0)
                        ],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )


async def test_reused_limit_policy_counts_per_assignment(db_session: AsyncSession) -> None:
    (
        actor,
        scope,
        team,
        first_project,
        provider,
        pool,
        fast_model,
        _,
    ) = await _create_project_pool_and_models(db_session)
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
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
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
                policy_id=access.policy_id,
                scope_type="project",
                project_id=project.id,
            ),
            scope=scope,
            db=db_session,
        )
        await policies_facade.create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_type="limit",
                policy_id=limit.policy_id,
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

    await gateway_limits.enforce_limit_policies(
        resolved=second_resolved,
        estimated_input_tokens=1,
        requested_output_tokens=0,
        db=db_session,
    )
    with pytest.raises(gateway_limits.GatewayLimitDeniedError) as exc:
        await gateway_limits.enforce_limit_policies(
            resolved=first_resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"


async def test_policy_activity_events_cover_mutations(db_session: AsyncSession) -> None:
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
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Activity access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                    public_model_name="fast",
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    access = await policies_facade.update_access_policy(
        policy_id=access.id,
        payload=UpdateAccessPolicyRequest(description="updated"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(name="Activity limits"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    limit = await policies_facade.update_limit_policy(
        policy_id=limit.id,
        payload=UpdateLimitPolicyRequest(description="updated"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    rule = await policies_facade.create_limit_policy_rule(
        policy_id=limit.id,
        payload=CreateLimitPolicyRuleRequest(
            name="Requests",
            limit_type="requests",
            limit_value=10,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    rule = await policies_facade.update_limit_policy_rule(
        rule_id=rule.id,
        payload=UpdateLimitPolicyRuleRequest(limit_value=12),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            team_id=team.id,
            project_id=project.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.update_policy_assignment(
        assignment_id=assignment.id,
        payload=UpdatePolicyAssignmentRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.delete_policy_assignment(
        assignment_id=assignment.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.delete_limit_policy_rule(
        rule_id=rule.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.delete_limit_policy(
        policy_id=limit.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.delete_access_policy(
        policy_id=access.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )

    actions = set(
        await db_session.scalars(
            select(ActivityEvent.action).where(
                ActivityEvent.org_id == scope.org_id,
                ActivityEvent.category == "policy",
            )
        )
    )
    assert {
        "access_policy.created",
        "access_policy.updated",
        "access_policy.deleted",
        "limit_policy.created",
        "limit_policy.updated",
        "limit_policy.deleted",
        "limit_rule.created",
        "limit_rule.updated",
        "limit_rule.deleted",
        "policy_assignment.created",
        "policy_assignment.updated",
        "policy_assignment.deleted",
    }.issubset(actions)


async def test_policy_impact_reports_affected_targets_and_unusable_keys(
    db_session: AsyncSession,
) -> None:
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
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Project access",
            public_models=[
                _public_model_route(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_id=[fast_model.id],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access.policy_id,
            scope_type="project",
            team_id=team.id,
            project_id=project.id,
        ),
        scope=scope,
        db=db_session,
    )
    key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Runtime key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    impact = await policies_facade.get_access_policy_impact(
        policy_id=access.id,
        scope=scope,
        db=db_session,
    )

    assert impact.affected_project_count == 1
    assert impact.affected_virtual_key_count == 1
    assert impact.affected_projects[0].id == project.id
    assert impact.affected_virtual_keys[0].id == key.id
    assert impact.virtual_keys_would_become_unusable_count == 1
    assert impact.virtual_keys_would_become_unusable[0].id == key.id




