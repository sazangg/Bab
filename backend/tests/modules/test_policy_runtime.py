from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.proxy import _enforce_limit_policies
from app.core.database import Scope
from app.core.security import hash_token
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import AuditEvent, Organization, Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    PolicyNotConfiguredError,
    ProjectAccessUnavailableError,
    ProjectInactiveError,
    ProjectNotFoundError,
    VirtualKeyAlreadyRevokedError,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.schemas import (
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
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
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    UpdateCredentialPoolRequest,
)
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
    assert key.revoked_reason == "Application credential was replaced"
    with pytest.raises(InvalidVirtualKeyError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=created_key.key, requested_model="fast"),
            db=db_session,
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

    assert page.total == 1005
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
    access = await policies_facade.create_access_policy(
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
    raw_key = "bab_test_empty_pool_route"
    db_session.add(
        VirtualKey(
            org_id=scope.org_id,
            project_id=project.id,
            name="Empty pool key",
            key_hash=hash_token(raw_key),
            key_prefix="bab_test_empty",
            created_by=actor.id,
        )
    )
    await db_session.commit()

    summary = await keys_facade.get_project_effective_access(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )
    project_models = await keys_facade.list_project_accessible_models(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )
    key_models = await keys_facade.list_accessible_models(raw_key=raw_key, db=db_session)

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=raw_key, requested_model="gpt-5.4-mini"),
            db=db_session,
        )

    assert summary.is_usable is False
    assert summary.blocking_code == "no_routable_provider_model"
    assert summary.routes == []
    assert project_models == []
    assert key_models == []


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
