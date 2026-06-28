from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.errors import (
    GuardrailAssignmentConflictError,
    GuardrailAssignmentTargetNotFoundError,
    GuardrailDeniedError,
)
from app.modules.guardrails.evaluation import (
    RuntimeGuardrailAssignmentRef,
    RuntimeGuardrailPolicyRef,
    RuntimeGuardrailRuleInput,
    RuntimeGuardrailRuleRef,
    RuntimeMatcherInput,
    evaluate_guardrail_rules_readonly,
)
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.guardrails.internal.models import GuardrailPolicy, GuardrailRule
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    GuardrailEvaluationContext,
    GuardrailRuleInput,
    GuardrailRuleMatcherInput,
    GuardrailSimulationRequest,
    UpdateGuardrailAssignmentRequest,
    UpdateGuardrailPolicyRequest,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.workspace.internal.models import Organization, Project, Team


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
        virtual_key_id=uuid4(),
        provider_id=uuid4(),
        pool_id=uuid4(),
        requested_model=model,
        provider_model=model,
    )


def _runtime_guardrail_rule(
    *,
    rule_type: str = "prompt_contains",
    effect: str = "deny",
    values: list[str] | None = None,
    matchers: list[RuntimeMatcherInput] | None = None,
    enforcement_mode: str = "enforce",
    assignment_mode: str = "enforce",
) -> RuntimeGuardrailRuleInput:
    return RuntimeGuardrailRuleInput(
        policy_ref=RuntimeGuardrailPolicyRef(
            policy_key="policy:test",
            policy_id=uuid4(),
            policy_revision_id=uuid4(),
            policy_name="Test guardrail",
            policy_revision_number=1,
            enforcement_mode=enforcement_mode,
        ),
        assignment_refs=[
            RuntimeGuardrailAssignmentRef(
                assignment_id=uuid4(),
                assignment_mode=assignment_mode,
                assignment_scope_type="team",
                assignment_scope_label="Platform",
            )
        ],
        rule_ref=RuntimeGuardrailRuleRef(
            rule_id=uuid4(),
            rule_name=None,
            rule_index=0,
        ),
        phase="request",
        source_phase="request",
        rule_type=rule_type,
        effect=effect,
        values=values or ["secret"],
        matchers=matchers or [],
    )


async def test_guardrail_readonly_evaluator_reports_block_without_events(
    db_session: AsyncSession,
) -> None:
    org_id = uuid4()
    context = _context(org_id=org_id, team_id=uuid4()).model_copy(
        update={"prompt_text": "contains a secret"}
    )

    results = await evaluate_guardrail_rules_readonly(
        context=context,
        rules=[_runtime_guardrail_rule()],
        detector_mode="execute_detectors",
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].denied is True
    assert results[0].decision == "blocked"
    assert results[0].reason_code == "prompt_contains_deny"
    assert results[0].matched_values == ["secret"]
    events = await guardrails_facade.list_events(scope=Scope(org_id=org_id), db=db_session)
    assert events == []


async def test_guardrail_readonly_evaluator_respects_matchers_and_detector_mode(
    db_session: AsyncSession,
) -> None:
    context = _context(org_id=uuid4(), team_id=uuid4()).model_copy(
        update={"prompt_text": "contains a secret", "public_model_name": "fast-general"}
    )

    skipped = await evaluate_guardrail_rules_readonly(
        context=context,
        rules=[
            _runtime_guardrail_rule(
                matchers=[
                    RuntimeMatcherInput(
                        dimension="public_model_name",
                        operator="eq",
                        value_json="slow-general",
                    )
                ],
            )
        ],
        detector_mode="execute_detectors",
        db=db_session,
    )
    applicability_only = await evaluate_guardrail_rules_readonly(
        context=context,
        rules=[
            _runtime_guardrail_rule(
                matchers=[
                    RuntimeMatcherInput(
                        dimension="public_model_name",
                        operator="eq",
                        value_json="fast-general",
                    )
                ],
            )
        ],
        detector_mode="applicability_only",
        db=db_session,
    )

    assert skipped[0].decision == "not_applicable"
    assert skipped[0].detector_evaluated is False
    assert applicability_only[0].decision == "not_evaluated"
    assert applicability_only[0].applicability_matched is True
    assert applicability_only[0].detector_evaluated is False


async def test_guardrail_prompt_allow_blocks_missing_prompt(db_session: AsyncSession) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Allowed prompts",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="allow",
                    values=["approved"],
                )
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

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
                update={"prompt_text": "missing marker"}
            ),
            db=db_session,
        )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "blocked"
    assert events[0].policy_revision_id == policy.rules[0].policy_revision_id


async def test_guardrail_event_decision_constraint_rejects_unknown_value(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)

    with pytest.raises(IntegrityError):
        await guardrails_repository.create_event(
            org_id=scope.org_id,
            policy_id=None,
            policy_revision_id=None,
            rule_id=None,
            decision="dry_run",
            phase="request",
            reason="legacy",
            team_id=team.id,
            project_id=uuid4(),
            virtual_key_id=uuid4(),
            provider_id=uuid4(),
            pool_id=uuid4(),
            request_id=None,
            requested_model="gpt-5-mini",
            provider_model="gpt-5-mini",
            metadata={},
            db=db_session,
        )
    await db_session.rollback()


async def test_guardrail_rule_matchers_round_trip(db_session: AsyncSession) -> None:
    actor, scope, _team = await _create_actor_scope(db_session)

    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Scoped prompt rule",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["secret"],
                    matchers=[
                        GuardrailRuleMatcherInput(
                            dimension="public_model_name",
                            operator="eq",
                            value_json="fast-general",
                        )
                    ],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    assert [
        (matcher.dimension, matcher.operator, matcher.value_json)
        for matcher in policy.rules[0].matchers
    ] == [("public_model_name", "eq", "fast-general")]

    listed = await guardrails_facade.list_policies(scope=scope, db=db_session)
    assert [
        (matcher.dimension, matcher.operator, matcher.value_json)
        for matcher in listed[0].rules[0].matchers
    ] == [("public_model_name", "eq", "fast-general")]


async def test_guardrail_policy_updates_create_new_active_revision(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team = await _create_actor_scope(db_session)

    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Revisioned guardrail",
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
    first_revision_id = policy.rules[0].policy_revision_id

    updated = await guardrails_facade.update_policy(
        policy_id=policy.id,
        payload=UpdateGuardrailPolicyRequest(
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["classified"],
                )
            ]
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    second_revision_id = updated.rules[0].policy_revision_id

    assert first_revision_id is not None
    assert second_revision_id is not None
    assert second_revision_id != first_revision_id
    stored_policy = await guardrails_repository.get_policy(
        policy_id=policy.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert stored_policy is not None
    assert stored_policy.policy_id is not None
    shared_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=stored_policy.policy_id,
        db=db_session,
    )
    assert shared_revision is not None
    assert shared_revision.id == second_revision_id
    assert shared_revision.revision_number == 2
    assert [rule.values for rule in updated.rules] == [["classified"]]


async def test_guardrail_policy_and_rules_require_shared_lifecycle_rows(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team = await _create_actor_scope(db_session)

    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Required shared lifecycle",
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
    stored_policy = await guardrails_repository.get_policy(
        policy_id=policy.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert stored_policy is not None
    assert stored_policy.policy_id is not None
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=stored_policy.policy_id,
        db=db_session,
    )
    assert active_revision is not None
    assert policy.rules[0].policy_revision_id == active_revision.id
    stored_policy_id = stored_policy.id

    db_session.add(
        GuardrailPolicy(
            org_id=scope.org_id,
            name="Missing shared policy",
            enforcement_mode="enforce",
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    db_session.add(
        GuardrailRule(
            org_id=scope.org_id,
            policy_id=stored_policy_id,
            rule_type="prompt_contains",
            effect="deny",
            phase="both",
            values=["orphan"],
            config={},
            priority=100,
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_guardrail_policy_assignment_is_canonical_assignment_record(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Assignment revisions",
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

    assignment = await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="team",
            team_id=team.id,
            enforcement_mode="dry_run",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    stored_assignment = await guardrails_repository.get_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    canonical_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert stored_assignment is not None
    assert canonical_assignment is not None
    assert stored_assignment.id == canonical_assignment.id == assignment.id
    assert canonical_assignment.policy_type == "guardrail"
    assert canonical_assignment.mode == "dry_run"
    assert canonical_assignment.scope_target_key == f"team:{team.id}"
    assert canonical_assignment.effective_to is None

    updated = await guardrails_facade.update_assignment(
        assignment_id=assignment.id,
        payload=UpdateGuardrailAssignmentRequest(enforcement_mode="enforce"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await db_session.refresh(canonical_assignment)
    replacement = await policy_kernel_repository.get_policy_assignment(
        assignment_id=updated.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert updated.id != assignment.id
    assert canonical_assignment.effective_to is not None
    assert canonical_assignment.superseded_by_assignment_id == replacement.id
    assert replacement.mode == "enforce"
    assert replacement.effective_to is None


async def test_guardrail_assignment_update_keeps_shared_assignment_scope_in_sync(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    other_team = Team(org_id=scope.org_id, name="Platform 2", slug=f"platform-2-{uuid4()}")
    db_session.add(other_team)
    await db_session.flush()
    project = Project(
        org_id=scope.org_id,
        team_id=other_team.id,
        created_by=actor.id,
        name="Moved project",
        slug=f"moved-{uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Assignment scope sync",
            rules=[GuardrailRuleInput(rule_type="prompt_contains", effect="deny", values=["x"])],
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
            enforcement_mode="dry_run",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    original_shared = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )

    updated = await guardrails_facade.update_assignment(
        assignment_id=assignment.id,
        payload=UpdateGuardrailAssignmentRequest(
            scope_type="project",
            project_id=project.id,
            enforcement_mode="enforce",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    stored = await guardrails_repository.get_assignment(
        assignment_id=updated.id,
        org_id=scope.org_id,
        db=db_session,
    )
    replacement = await policy_kernel_repository.get_policy_assignment(
        assignment_id=updated.id,
        org_id=scope.org_id,
        db=db_session,
    )

    await db_session.refresh(original_shared)
    assert original_shared.is_active is False
    assert original_shared.effective_to is not None
    assert original_shared.superseded_by_assignment_id == replacement.id
    assert stored.scope_type == replacement.scope_type == "project"
    assert stored.team_id is None and replacement.team_id is None
    assert stored.project_id == replacement.project_id == project.id
    assert stored.virtual_key_id is None and replacement.virtual_key_id is None
    assert replacement.scope_target_key == f"project:{project.id}"
    assert replacement.mode == "enforce"
    assert replacement.is_active is True


async def test_guardrail_runtime_ignores_closed_shared_assignment(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Closed shared assignment",
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
    stored_assignment = await guardrails_repository.get_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    shared_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=stored_assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    shared_assignment.is_active = False
    shared_assignment.effective_to = shared_assignment.effective_from
    await db_session.flush()

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={"prompt_text": "secret"}
        ),
        db=db_session,
    )


async def test_guardrail_rule_matchers_validate_stage_availability(
    db_session: AsyncSession,
) -> None:
    actor, scope, _team = await _create_actor_scope(db_session)

    with pytest.raises(ValueError):
        await guardrails_facade.create_policy(
            payload=CreateGuardrailPolicyRequest(
                name="Invalid matcher",
                rules=[
                    GuardrailRuleInput(
                        rule_type="prompt_contains",
                        effect="deny",
                        values=["secret"],
                        phase="request",
                        matchers=[
                            GuardrailRuleMatcherInput(
                                dimension="provider_credential_id",
                                operator="exists",
                            )
                        ],
                    )
                ],
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_guardrail_rule_matchers_filter_runtime_evaluation(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    provider_id = uuid4()
    other_provider_id = uuid4()
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Provider scoped prompt rule",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["secret"],
                    matchers=[
                        GuardrailRuleMatcherInput(
                            dimension="provider_id",
                            operator="eq",
                            value_json=str(provider_id),
                        )
                    ],
                )
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

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={
                "provider_id": other_provider_id,
                "prompt_text": "secret",
            }
        ),
        db=db_session,
    )
    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
                update={
                    "provider_id": provider_id,
                    "prompt_text": "secret",
                }
            ),
            db=db_session,
        )


async def test_guardrail_rule_matchers_filter_resolved_route_dimensions(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    route_candidate_id = uuid4()
    other_route_candidate_id = uuid4()
    public_model_id = uuid4()
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Route scoped prompt rule",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["secret"],
                    matchers=[
                        GuardrailRuleMatcherInput(
                            dimension="public_model_id",
                            operator="eq",
                            value_json=str(public_model_id),
                        ),
                        GuardrailRuleMatcherInput(
                            dimension="public_model_name",
                            operator="eq",
                            value_json="fast-general",
                        ),
                        GuardrailRuleMatcherInput(
                            dimension="route_candidate_id",
                            operator="eq",
                            value_json=str(route_candidate_id),
                        ),
                    ],
                )
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

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={
                "prompt_text": "secret",
                "public_model_id": public_model_id,
                "public_model_name": "fast-general",
                "route_candidate_id": other_route_candidate_id,
            }
        ),
        db=db_session,
    )
    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
                update={
                    "prompt_text": "secret",
                    "public_model_id": public_model_id,
                    "public_model_name": "fast-general",
                    "route_candidate_id": route_candidate_id,
                }
            ),
            db=db_session,
        )


async def test_guardrail_monitor_mode_records_warning_without_blocking(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Monitor provider",
            enforcement_mode="monitor",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={"prompt_text": "blocked"}
        ),
        db=db_session,
    )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "allowed"
    assert events[1].decision == "would_block"


async def test_guardrail_assignment_dry_run_records_without_blocking(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Dry run provider",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
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
            enforcement_mode="dry_run",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={"prompt_text": "blocked"}
        ),
        db=db_session,
    )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "allowed"
    assert events[1].decision == "would_block"


async def test_guardrail_enforce_assignment_is_not_weakened_by_dry_run_scope(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Mixed assignment mode",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type="team",
            team_id=team.id,
            enforcement_mode="dry_run",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
                update={"prompt_text": "blocked"}
            ),
            db=db_session,
        )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "blocked"


async def test_has_enforced_response_guardrails_uses_effective_mode(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    monitor_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Monitor response",
            enforcement_mode="monitor",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    phase="response",
                    values=["blocked"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=monitor_policy.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    context = _context(org_id=scope.org_id, team_id=team.id)

    assert (
        await guardrails_facade.has_enforced_response_guardrails(
            context=context,
            db=db_session,
        )
        is False
    )

    dry_run_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Dry-run response",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    phase="response",
                    values=["blocked"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=dry_run_policy.id,
            scope_type="team",
            team_id=team.id,
            enforcement_mode="dry_run",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    assert (
        await guardrails_facade.has_enforced_response_guardrails(
            context=context,
            db=db_session,
        )
        is False
    )

    blocking_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Blocking response",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    phase="response",
                    values=["blocked"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=blocking_policy.id,
            scope_type="team",
            team_id=team.id,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    assert (
        await guardrails_facade.has_enforced_response_guardrails(
            context=context,
            db=db_session,
        )
        is True
    )


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
                    rule_type="prompt_contains",
                    effect="allow",
                    values=["approved"],
                    priority=10,
                ),
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                    matchers=[
                        GuardrailRuleMatcherInput(
                            dimension="provider_id",
                            operator="eq",
                            value_json=str(provider_id),
                        )
                    ],
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
    context.prompt_text = "approved but blocked"

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(context=context, db=db_session)

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].decision == "blocked"
    assert events[0].reason == "prompt_contains_deny"


async def test_guardrail_rejects_duplicate_assignment_for_same_policy_scope(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Duplicate guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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


async def test_guardrail_rejects_assignment_to_missing_target(db_session: AsyncSession) -> None:
    actor, scope, _team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Target guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(GuardrailAssignmentTargetNotFoundError):
        await guardrails_facade.create_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=policy.id,
                scope_type="team",
                team_id=uuid4(),
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_guardrail_assignment_validates_project_and_key_ownership(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    _other_actor, other_scope, other_team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Ownership guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project = Project(
        org_id=scope.org_id,
        team_id=team.id,
        created_by=actor.id,
        name="Guarded project",
        slug=f"guarded-{uuid4()}",
    )
    other_project = Project(
        org_id=other_scope.org_id,
        team_id=other_team.id,
        created_by=actor.id,
        name="Other project",
        slug=f"other-{uuid4()}",
    )
    db_session.add_all([project, other_project])
    await db_session.flush()
    virtual_key = VirtualKey(
        org_id=scope.org_id,
        project_id=project.id,
        name="Guarded key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab_test_guard",
        created_by=actor.id,
    )
    db_session.add(virtual_key)
    await db_session.flush()
    project_id = project.id
    other_project_id = other_project.id
    virtual_key_id = virtual_key.id
    team_id = team.id
    await db_session.commit()

    with pytest.raises(GuardrailAssignmentTargetNotFoundError):
        await guardrails_facade.create_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=policy.id,
                scope_type="project",
                team_id=other_team.id,
                project_id=project_id,
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    with pytest.raises(GuardrailAssignmentTargetNotFoundError):
        await guardrails_facade.create_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=policy.id,
                scope_type="virtual_key",
                project_id=other_project_id,
                virtual_key_id=virtual_key_id,
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )
    with pytest.raises(GuardrailAssignmentTargetNotFoundError):
        await guardrails_facade.create_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=policy.id,
                scope_type="org",
                team_id=team_id,
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_deleted_assignment_no_longer_enforces_policy(db_session: AsyncSession) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Temporary guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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
    stored_assignment = await guardrails_repository.get_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert stored_assignment is not None
    shared_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=stored_assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert shared_assignment is not None
    await guardrails_facade.delete_assignment(
        assignment_id=assignment.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await db_session.refresh(shared_assignment)
    assert shared_assignment.effective_to is not None
    assert shared_assignment.is_active is False

    await guardrails_facade.evaluate_request(
        context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
            update={"prompt_text": "blocked"}
        ),
        db=db_session,
    )


async def test_deleted_policy_closes_shared_assignments(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Deleted guardrail policy",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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
    stored_assignment = await guardrails_repository.get_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    shared_assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=stored_assignment.id,
        org_id=scope.org_id,
        db=db_session,
    )
    stored_policy = await guardrails_repository.get_policy(
        policy_id=policy.id,
        org_id=scope.org_id,
        db=db_session,
    )
    shared_policy_id = stored_policy.policy_id

    await guardrails_facade.delete_policy(
        policy_id=policy.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await db_session.refresh(shared_assignment)
    shared_policy = await policy_kernel_repository.get_policy(
        org_id=scope.org_id,
        policy_id=shared_policy_id,
        db=db_session,
    )
    stored_policy_after_delete = await guardrails_repository.get_policy(
        policy_id=policy.id,
        org_id=scope.org_id,
        db=db_session,
    )
    assert shared_assignment.effective_to is not None
    assert shared_assignment.is_active is False
    assert shared_policy.is_active is False
    assert stored_policy_after_delete is not None
    assert stored_policy_after_delete.is_active is False


async def test_guardrail_impact_reports_assignment_targets(db_session: AsyncSession) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    project = Project(
        org_id=scope.org_id,
        team_id=team.id,
        created_by=actor.id,
        name="Console",
        slug=f"console-{uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()
    key = VirtualKey(
        org_id=scope.org_id,
        project_id=project.id,
        name="Runtime key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    db_session.add(key)
    await db_session.commit()
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Impact policy",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
            ],
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

    policy_impact = await guardrails_facade.get_policy_impact(
        policy_id=policy.id,
        scope=scope,
        db=db_session,
    )
    assignment_impact = await guardrails_facade.get_assignment_impact(
        assignment_id=assignment.id,
        scope=scope,
        db=db_session,
    )

    assert policy_impact.affected_team_count == 1
    assert policy_impact.affected_project_count == 1
    assert policy_impact.affected_virtual_key_count == 1
    assert policy_impact.affected_virtual_keys[0].id == key.id
    assert assignment_impact.affected_projects[0].id == project.id


async def test_guardrail_events_can_be_filtered_by_policy_and_model(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Event filters",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["blocked"],
                )
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

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id, model="gpt-5-large").model_copy(
                update={"prompt_text": "blocked"}
            ),
            db=db_session,
        )

    events = await guardrails_facade.list_events(
        scope=scope,
        policy_id=policy.id,
        model="large",
        db=db_session,
    )
    assert len(events) == 1
    assert events[0].policy_id == policy.id
    assert events[0].requested_model == "gpt-5-large"


async def test_guardrail_prompt_contains_blocks_matching_prompt(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="Prompt guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    values=["internal roadmap"],
                )
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

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(
                org_id=scope.org_id,
                team_id=team.id,
                model="gpt-5-mini",
            ).model_copy(update={"prompt_text": "Summarize the internal roadmap"}),
            db=db_session,
        )


async def test_guardrail_simulation_reports_pii_match(db_session: AsyncSession) -> None:
    _actor, scope, _team = await _create_actor_scope(db_session)

    result = await guardrails_facade.simulate(
        payload=GuardrailSimulationRequest(
            rules=[
                GuardrailRuleInput(
                    rule_type="pii",
                    effect="deny",
                    values=["email", "credit_card"],
                )
            ],
            requested_model="gpt-5-mini",
            prompt_text="Contact alice@example.com for approval.",
        ),
        scope=scope,
        db=db_session,
    )

    assert result.decision == "blocked"
    assert result.matches[0].matched_values == ["email"]


async def test_guardrail_pii_event_metadata_uses_safe_labels(
    db_session: AsyncSession,
) -> None:
    actor, scope, team = await _create_actor_scope(db_session)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(
            name="PII event guard",
            rules=[
                GuardrailRuleInput(
                    rule_type="pii",
                    effect="deny",
                    values=["email"],
                )
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

    with pytest.raises(GuardrailDeniedError):
        await guardrails_facade.evaluate_request(
            context=_context(org_id=scope.org_id, team_id=team.id).model_copy(
                update={"prompt_text": "Contact alice@example.com for approval."}
            ),
            db=db_session,
        )

    events = await guardrails_facade.list_events(scope=scope, db=db_session)
    assert events[0].metadata["pii_types"] == ["email"]
    assert events[0].metadata["matched_values_redacted"] is True
    assert "matched_values" not in events[0].metadata
    assert "alice@example.com" not in str(events[0].metadata)


async def test_guardrail_simulation_reports_allowlist_miss(db_session: AsyncSession) -> None:
    _actor, scope, _team = await _create_actor_scope(db_session)

    result = await guardrails_facade.simulate(
        payload=GuardrailSimulationRequest(
            requested_model="gpt-5-large",
            prompt_text="missing marker",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="allow",
                    values=["approved"],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.decision == "blocked"
    assert result.matches[0].reason == "prompt_contains_allowlist_miss"
    assert result.matches[0].matched_values == []


async def test_guardrail_simulation_ignores_response_only_rules(
    db_session: AsyncSession,
) -> None:
    _actor, scope, _team = await _create_actor_scope(db_session)

    result = await guardrails_facade.simulate(
        payload=GuardrailSimulationRequest(
            requested_model="gpt-5-mini",
            prompt_text="contains blocked output",
            rules=[
                GuardrailRuleInput(
                    rule_type="prompt_contains",
                    effect="deny",
                    phase="response",
                    values=["blocked output"],
                )
            ],
        ),
        scope=scope,
        db=db_session,
    )

    assert result.decision == "allowed"
    assert result.matches == []


async def test_guardrail_pii_rule_uses_configured_detector(db_session: AsyncSession) -> None:
    _actor, scope, _team = await _create_actor_scope(db_session)

    result = await guardrails_facade.simulate(
        payload=GuardrailSimulationRequest(
            rules=[
                GuardrailRuleInput(
                    rule_type="pii",
                    effect="deny",
                    values=["email"],
                    config={"detector": "missing_detector"},
                )
            ],
            requested_model="gpt-5-mini",
            prompt_text="Contact alice@example.com for approval.",
        ),
        scope=scope,
        db=db_session,
    )

    assert result.decision == "allowed"


def test_guardrail_rule_input_rejects_invalid_regex() -> None:
    with pytest.raises(ValidationError):
        GuardrailRuleInput(rule_type="prompt_regex", effect="deny", values=["["])


def test_guardrail_rule_input_rejects_unsupported_pii_values() -> None:
    with pytest.raises(ValidationError):
        GuardrailRuleInput(rule_type="pii", effect="deny", values=["passport"])


def test_guardrail_rule_input_rejects_routing_rule_types() -> None:
    with pytest.raises(ValidationError):
        GuardrailRuleInput(
            rule_type="provider",
            effect="deny",
            values=[str(uuid4())],
        )
