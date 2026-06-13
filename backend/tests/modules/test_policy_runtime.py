from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.projects import create_virtual_key as create_virtual_key_route
from app.api.v1.routes.proxy import ProxyLimitExceededError, _enforce_limit_policies
from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import AuditEvent, Organization, Team, User
from app.modules.auth.schemas import AuthenticatedUser
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
    VirtualKeyOverlapActiveError,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.schemas import (
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessRequest,
    RotateVirtualKeyRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
)
from app.modules.policies import facade as policies_facade
from app.modules.policies.errors import (
    PolicyAssignmentConflictError,
    PolicyNotFoundError,
    PolicyValidationError,
)
from app.modules.policies.schemas import (
    AccessPolicyRouteInput,
    CreateAccessPolicyRequest,
    CreateAccessPolicyRouteRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    LimitPolicyRuleInput,
    UpdateAccessPolicyRequest,
    UpdateAccessPolicyRouteRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    UpdateCredentialPoolRequest,
    UpdateModelOfferingRequest,
    UpdateProviderRequest,
)
from app.modules.settings import facade as settings_facade
from app.modules.settings.schemas import UpdateOrganizationSettingsRequest
from app.modules.teams.errors import TeamInactiveError
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import RecordUsage


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


async def test_authenticated_key_use_is_recorded_before_policy_denial(
    db_session: AsyncSession,
) -> None:
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
        event.metadata_.get("changed_fields", {}).get("name", {}).get("to")
        == "Renamed event key"
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
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
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
    actor, scope, _, project, provider, _, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
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
                routes=[
                    AccessPolicyRouteInput(
                        provider_id=provider.id,
                        credential_pool_id=empty_pool.id,
                        model_offering_ids=[fast_model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )


async def test_access_route_validation_blocks_inactive_provider_pool_and_model(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team, _project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )

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
        payload=UpdateModelOfferingRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(PolicyValidationError):
        await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name="Inactive model access",
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
    key_count = await db_session.scalar(
        select(func.count()).select_from(VirtualKey).where(VirtualKey.project_id == project.id)
    )
    assert key_count == 0


async def test_virtual_key_creation_is_blocked_when_secret_delivery_is_disabled(
    db_session: AsyncSession,
) -> None:
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
    actor, scope, _team, project, _provider, _pool, _fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )

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


async def test_same_project_access_policies_union_routes(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team, project, provider, pool, fast_model, large_model = (
        await _create_project_pool_and_models(db_session)
    )
    access_policies = []
    for model in (fast_model, large_model):
        access = await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name=f"Project access {model.provider_model_name}",
                routes=[
                    AccessPolicyRouteInput(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_ids=[model.id],
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
                access_policy_id=access.id,
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
        policy.id for policy in access_policies
    }
    assert {route.access_policy_id for route in summary.routes} == {
        policy.id for policy in access_policies
    }
    assert (
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
        )
    ).provider_model == "gpt-5.4-mini"
    assert (
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="gpt-5.5"),
            db=db_session,
        )
    ).provider_model == "gpt-5.5"


async def test_access_narrows_through_org_team_project_and_virtual_key(
    db_session: AsyncSession,
) -> None:
    actor, scope, team, project, provider, pool, fast_model, large_model = (
        await _create_project_pool_and_models(db_session)
    )
    org_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Org access",
            routes=[
                AccessPolicyRouteInput(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_ids=[fast_model.id, large_model.id],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    team_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Team access",
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
    project_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Project tries to broaden",
            routes=[
                AccessPolicyRouteInput(
                    provider_id=provider.id,
                    credential_pool_id=pool.id,
                    model_offering_ids=[fast_model.id, large_model.id],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )
    key_access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Key access",
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
    for payload in (
        CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=org_access.id,
            scope_type="org",
        ),
        CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=team_access.id,
            scope_type="team",
            team_id=team.id,
        ),
        CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=project_access.id,
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
            access_policy_id=key_access.id,
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

    assert [model.id for model in key_models] == ["gpt-5.4-mini"]
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
    actor, scope, team, project, provider, pool, fast_model, large_model = (
        await _create_project_pool_and_models(db_session)
    )
    for name, model, scope_type, target in (
        ("Org fast", fast_model, "org", {}),
        ("Org large", large_model, "org", {}),
        ("Team fast", fast_model, "team", {"team_id": team.id}),
        ("Project large only", large_model, "project", {"project_id": project.id}),
    ):
        access = await policies_facade.create_access_policy(
            payload=CreateAccessPolicyRequest(
                name=name,
                routes=[
                    AccessPolicyRouteInput(
                        provider_id=provider.id,
                        credential_pool_id=pool.id,
                        model_offering_ids=[model.id],
                    )
                ],
            ),
            scope=scope,
            db=db_session,
        )
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
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    _other_actor, _other_scope, other_team, other_project, *_ = (
        await _create_project_pool_and_models(db_session)
    )
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Scoped access",
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
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=access.id,
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
                access_policy_id=access.id,
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
                access_policy_id=access.id,
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
                access_policy_id=access.id,
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
                access_policy_id=access.id,
                scope_type="team",
                team_id=other_team.id,
            ),
            scope=scope,
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

    with pytest.raises(ProxyLimitExceededError) as exc:
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
    with pytest.raises(ProxyLimitExceededError) as exc:
        await _enforce_limit_policies(
            resolved=first_resolved,
            estimated_input_tokens=1,
            requested_output_tokens=0,
            db=db_session,
        )

    assert exc.value.detail == "limit policy request limit exceeded"


async def test_policy_activity_events_cover_mutations(db_session: AsyncSession) -> None:
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(name="Activity access"),
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
    route = await policies_facade.create_access_policy_route(
        policy_id=access.id,
        payload=CreateAccessPolicyRouteRequest(
            provider_id=provider.id,
            credential_pool_id=pool.id,
            model_offering_ids=[fast_model.id],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await policies_facade.update_access_policy_route(
        route_id=route.id,
        payload=UpdateAccessPolicyRouteRequest(priority=25),
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
    await policies_facade.update_limit_policy_rule(
        rule_id=rule.id,
        payload=UpdateLimitPolicyRuleRequest(limit_value=12),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=access.id,
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
    await policies_facade.delete_access_policy_route(
        route_id=route.id,
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
        "access_route.created",
        "access_route.updated",
        "access_route.deleted",
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
    actor, scope, team, project, provider, pool, fast_model, _ = (
        await _create_project_pool_and_models(db_session)
    )
    access = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(
            name="Project access",
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
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            access_policy_id=access.id,
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
