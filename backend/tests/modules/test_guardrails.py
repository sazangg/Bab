from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.errors import GuardrailAssignmentConflictError, GuardrailDeniedError
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    GuardrailEvaluationContext,
    GuardrailRuleInput,
)


async def _create_actor_scope(db_session: AsyncSession):
    org = Organization(name=f"Guardrails {uuid4()}", slug=f"guardrails-{uuid4()}")
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


def _context(*, org_id, team_id, model: str = "gpt-5-mini") -> GuardrailEvaluationContext:
    return GuardrailEvaluationContext(
        org_id=org_id,
        team_id=team_id,
        project_id=uuid4(),
        allocation_id=uuid4(),
        allocation_chain_ids=[uuid4()],
        virtual_key_id=uuid4(),
        provider_id=uuid4(),
        pool_id=uuid4(),
        requested_model=model,
        provider_model=model,
    )


async def test_guardrail_model_allow_blocks_outside_model(db_session: AsyncSession) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Allowed models",
            rules=[GuardrailRuleInput(rule_type="model", effect="allow", values=["gpt-5-mini"])],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id, model="gpt-5-large"),
            db=db_session,
        )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "blocked"


async def test_guardrail_monitor_mode_records_warning_without_blocking(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Monitor provider",
            enforcement_mode="monitor",
            rules=[GuardrailRuleInput(rule_type="model", effect="deny", values=["gpt-5-large"])],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="org",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id, model="gpt-5-large"),
        db=db_session,
    )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "allowed"
    assert events[1].decision == "warned"


async def test_guardrail_policy_blocks_when_any_enabled_rule_denies(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    provider_id = uuid4()
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Composite policy",
            rules=[
                GuardrailRuleInput(
                    rule_type="model",
                    effect="allow",
                    values=["gpt-5-mini"],
                    priority=10,
                ),
                GuardrailRuleInput(
                    rule_type="provider",
                    effect="deny",
                    values=[str(provider_id)],
                    priority=20,
                ),
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    context = _context(org_id=scope.org_id, team_id=team.id, model="gpt-5-mini")
    context.provider_id = provider_id

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(context=context, db=db_session)

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "blocked"
    assert events[0].reason == "provider_deny"


async def test_guardrail_rejects_duplicate_assignment_for_same_policy_scope(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Duplicate guard",
            rules=[GuardrailRuleInput(rule_type="model", effect="deny", values=["gpt-5-large"])],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    payload = CreateGuardrailAssignmentRequest(
        policy_id=policy.id,
        scope_type="team",
        team_id=team.id,
    )
    await guardrails_facade.create_assignment(
        payload=payload,
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(GuardrailAssignmentConflictError):
        await guardrails_facade.create_assignment(
            payload=payload,
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_deleted_assignment_no_longer_enforces_policy(db_session: AsyncSession) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Temporary guard",
            rules=[GuardrailRuleInput(rule_type="model", effect="deny", values=["gpt-5-large"])],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assignment = await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.delete_assignment(
        assignment_id=assignment.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id, model="gpt-5-large"),
        db=db_session,
    )
