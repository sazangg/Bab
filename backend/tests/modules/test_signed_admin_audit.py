import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, Scope
from app.modules.auth.internal.models import AuditEvent, AuditLedgerState, Organization
from app.modules.auth.internal.service import (
    list_audit_events,
    record_audit_event,
    verify_audit_chain,
)
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
)
from app.modules.keys import facade as keys_facade
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.schemas import CreateProjectRequest, UpdateVirtualKeyRequest
from app.modules.policies import facade as policies_facade
from app.modules.policies.schemas import CreateAccessPolicyRequest, CreatePolicyAssignmentRequest
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import CreateProviderRequest
from app.modules.settings import facade as settings_facade
from app.modules.settings.schemas import UpdateOrganizationSettingsRequest
from app.modules.teams import facade as teams_facade
from app.modules.teams.schemas import CreateTeamRequest


async def _actor_scope(db_session: AsyncSession) -> tuple[AuthenticatedUser, Scope]:
    org = Organization(name=f"Audit {uuid4()}", slug=f"audit-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    return (
        AuthenticatedUser(
            id=uuid4(),
            org_id=org.id,
            email="admin@example.com",
            role="org_admin",
            permissions=["*"],
        ),
        Scope(org_id=org.id),
    )


@pytest.mark.asyncio
async def test_admin_mutations_write_signed_audit_events(db_session: AsyncSession) -> None:
    actor, scope = await _actor_scope(db_session)

    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.example/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Platform"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project = await keys_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Console"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    access_policy = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(name="Default access"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assignment = await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=access_policy.policy_id,
            scope_type="project",
            project_id=project.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    seeded_key = VirtualKey(
        org_id=scope.org_id,
        project_id=project.id,
        name="Console key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    db_session.add(seeded_key)
    await db_session.commit()
    virtual_key = await keys_facade.update_virtual_key(
        project_id=project.id,
        key_id=seeded_key.id,
        payload=UpdateVirtualKeyRequest(name="Renamed console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await settings_facade.update_organization_settings(
        payload=UpdateOrganizationSettingsRequest(organization_name="Signed Audit Labs"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    guardrail_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(name="PII guardrail"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    guardrail_assignment = await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=guardrail_policy.id,
            scope_type="project",
            project_id=project.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    events = await _audit_events(db_session, scope.org_id)
    events_by_action = {event.action: event for event in events}
    expected = {
        "provider.created": ("provider", provider.id),
        "team.created": ("team", team.id),
        "project.created": ("project", project.id),
        "virtual_key.updated": ("virtual_key", virtual_key.id),
        "policy_assignment.created": ("policy_assignment", assignment.id),
        "settings.updated": ("organization", None),
        "guardrail.policy_created": ("guardrail_policy", guardrail_policy.id),
        "guardrail.assignment_created": ("guardrail_assignment", guardrail_assignment.id),
    }

    for action, (entity_type, entity_id) in expected.items():
        event = events_by_action[action]
        assert event.actor_user_id == actor.id
        assert event.actor_email == str(actor.email)
        assert event.action == action
        assert event.entity_type == entity_type
        assert event.entity_id == entity_id
        assert event.event_hash
        assert event.signature_algorithm == "hmac-sha256"
        if action != "provider.created":
            assert event.previous_hash

    verification = await verify_audit_chain(scope=scope, db=db_session)
    assert verification.valid is True
    assert verification.checked_events == len(events)
    ledger_state = await db_session.get(AuditLedgerState, scope.org_id)
    assert ledger_state is not None
    assert ledger_state.latest_event_hash == events[-1].event_hash


@pytest.mark.asyncio
async def test_sequential_signed_audit_appends_keep_chain_valid(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _actor_scope(db_session)

    for index in range(5):
        await record_audit_event(
            actor=actor,
            action=f"test.event_{index}",
            entity_type="organization",
            entity_id=None,
            metadata={"index": index},
            db=db_session,
        )
    await db_session.commit()

    events = await _audit_events(db_session, scope.org_id)
    for previous, current in zip(events, events[1:], strict=False):
        assert current.previous_hash == previous.event_hash
    verification = await verify_audit_chain(scope=scope, db=db_session)
    assert verification.valid is True
    assert verification.checked_events == 5


@pytest.mark.asyncio
async def test_concurrent_signed_audit_appends_file_sqlite_serializes_without_fork(
    tmp_path,
) -> None:
    # SQLite does not model row-level locking like Postgres, but a file-backed database with
    # separate sessions still exercises concurrent transaction boundaries for this regression.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'audit-concurrency.db'}",
        connect_args={"timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    org_id = uuid4()
    async with session_factory() as session:
        session.add(Organization(id=org_id, name="Concurrent Audit", slug=f"audit-{uuid4()}"))
        await record_audit_event(
            actor=AuthenticatedUser(
                id=uuid4(),
                org_id=org_id,
                email="seed@example.com",
                role="org_admin",
                permissions=["*"],
            ),
            action="concurrent.seed",
            entity_type="organization",
            entity_id=None,
            metadata={},
            db=session,
        )
        await session.commit()

    async def append_event(index: int) -> None:
        async with session_factory() as session:
            await record_audit_event(
                actor=AuthenticatedUser(
                    id=uuid4(),
                    org_id=org_id,
                    email=f"admin-{index}@example.com",
                    role="org_admin",
                    permissions=["*"],
                ),
                action=f"concurrent.event_{index}",
                entity_type="organization",
                entity_id=None,
                metadata={"index": index},
                db=session,
            )
            await session.commit()

    try:
        await asyncio.gather(*(append_event(index) for index in range(8)))
        async with session_factory() as session:
            events = await _audit_events(session, org_id)
            verification = await verify_audit_chain(scope=Scope(org_id=org_id), db=session)
    finally:
        await engine.dispose()

    concurrent_events = [event for event in events if event.action.startswith("concurrent.event_")]
    assert {event.action for event in concurrent_events} == {
        f"concurrent.event_{index}" for index in range(8)
    }
    assert all(event.previous_hash for event in concurrent_events)
    assert all(event.event_hash for event in concurrent_events)
    assert verification.valid is True
    previous_hashes = [event.previous_hash for event in events if event.previous_hash is not None]
    assert len(previous_hashes) == len(set(previous_hashes))


@pytest.mark.asyncio
async def test_audit_verify_detects_tampering_duplicate_previous_hash_and_unreachable_events(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _actor_scope(db_session)
    for index in range(3):
        await record_audit_event(
            actor=actor,
            action=f"test.event_{index}",
            entity_type="organization",
            entity_id=None,
            metadata={"index": index},
            db=db_session,
        )
    await db_session.commit()

    events = await _audit_events(db_session, scope.org_id)
    events[1].metadata_ = {"index": "tampered"}
    assert (await verify_audit_chain(scope=scope, db=db_session)).reason == "event hash mismatch"

    events[1].metadata_ = {"index": 1}
    events[2].previous_hash = events[0].previous_hash
    duplicate = await verify_audit_chain(scope=scope, db=db_session)
    assert duplicate.valid is False
    assert duplicate.reason == "duplicate previous hash"

    events[2].previous_hash = "unreachable"
    unreachable = await verify_audit_chain(scope=scope, db=db_session)
    assert unreachable.valid is False
    assert unreachable.reason == "chain has unreachable events"


@pytest.mark.asyncio
async def test_audit_search_and_cursor_use_selected_fields(db_session: AsyncSession) -> None:
    actor, scope = await _actor_scope(db_session)
    await record_audit_event(
        actor=actor,
        action="member.created",
        entity_type="user",
        entity_id=uuid4(),
        metadata={"email": "older@example.com", "status": "active"},
        db=db_session,
    )
    await db_session.flush()
    events = await _audit_events(db_session, scope.org_id)
    events[-1].created_at = events[-1].created_at.replace(microsecond=100)
    await record_audit_event(
        actor=actor,
        action="member.created",
        entity_type="user",
        entity_id=uuid4(),
        metadata={"email": "newer@example.com", "status": "active"},
        db=db_session,
    )
    await db_session.commit()

    first_page = await list_audit_events(
        scope=scope,
        db=db_session,
        search="example.com",
        limit=1,
    )
    assert len(first_page) == 1
    second_page = await list_audit_events(
        scope=scope,
        db=db_session,
        search="example.com",
        before_at=first_page[0].created_at,
        before_id=first_page[0].id,
        limit=1,
    )
    assert len(second_page) == 1
    assert second_page[0].id != first_page[0].id


async def _audit_events(db_session: AsyncSession, org_id: UUID) -> list[AuditEvent]:
    return list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    )

