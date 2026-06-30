from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, sqlite_write_unit, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import AuthorizationTarget
from app.modules.guardrails.errors import (
    GuardrailAssignmentConflictError,
    GuardrailAssignmentNotFoundError,
    GuardrailAssignmentTargetNotFoundError,
    GuardrailDeniedError,
    GuardrailPolicyNotFoundError,
)
from app.modules.guardrails.evaluation import (
    GUARDRAIL_SCAN_CHAR_LIMIT as _GUARDRAIL_SCAN_CHAR_LIMIT,
)
from app.modules.guardrails.evaluation import (
    GuardrailReadonlyEvaluation,
    RuntimeGuardrailAssignmentRef,
    RuntimeGuardrailPolicyRef,
    RuntimeGuardrailRuleInput,
    RuntimeGuardrailRuleRef,
    RuntimeMatcherInput,
    evaluate_guardrail_rules_readonly,
    matched_regex_values,
)
from app.modules.guardrails.internal import repository
from app.modules.guardrails.internal.models import GuardrailEvent
from app.modules.guardrails.internal.repository import GuardrailAssignmentView
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    GuardrailAssignmentResponse,
    GuardrailEvaluationContext,
    GuardrailEventResponse,
    GuardrailImpactResponse,
    GuardrailImpactTarget,
    GuardrailImpactVirtualKey,
    GuardrailPolicyOptionResponse,
    GuardrailPolicyResponse,
    GuardrailRuleMatcherResponse,
    GuardrailRuleResponse,
    GuardrailSimulationMatch,
    GuardrailSimulationRequest,
    GuardrailSimulationResponse,
    UpdateGuardrailAssignmentRequest,
    UpdateGuardrailPolicyRequest,
)
from app.modules.guardrails.validation import validate_guardrail_rule_payload
from app.modules.policy_kernel import (
    assignment_scope_specificity,
    assignment_scope_target_key,
    create_initial_active_revision,
    create_next_active_revision,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import Policy, PolicyAssignment
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceScopeNotFoundError

GUARDRAIL_SCAN_CHAR_LIMIT = _GUARDRAIL_SCAN_CHAR_LIMIT
_matched_regex_values = matched_regex_values


@dataclass(frozen=True)
class GuardrailDecisionTrace:
    policy_id: UUID | None
    policy_revision_id: UUID | None
    assignment_id: UUID | None
    assignment_mode: str | None
    assignment_scope_type: str | None
    assignment_team_id: UUID | None
    assignment_project_id: UUID | None
    assignment_virtual_key_id: UUID | None
    rule_id: UUID | None
    reason_code: str
    message: str | None


@dataclass(frozen=True)
class GuardrailEvaluationResult:
    evaluated: bool
    would_deny: list[GuardrailDecisionTrace]

    def __bool__(self) -> bool:
        return self.evaluated


async def list_policies(
    *,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> list[GuardrailPolicyResponse]:
    policies = await repository.list_policies(org_id=scope.org_id, db=db)
    if actor is not None and not _has_global_guardrail_visibility(actor):
        assignments = await _visible_assignments(actor=actor, scope=scope, db=db)
        visible_policy_ids = {assignment.policy_id for assignment in assignments}
        policies = [policy for policy in policies if policy.id in visible_policy_ids]
    rules = await repository.list_policy_rules(
        org_id=scope.org_id,
        policy_ids=[policy.id for policy in policies],
        db=db,
    )
    rules_by_policy = _rules_by_policy(rules)
    return [
        await _to_policy_response(policy, rules_by_policy.get(policy.id, []), scope=scope, db=db)
        for policy in policies
    ]


async def list_policy_options(
    *, scope: Scope, db: AsyncSession
) -> list[GuardrailPolicyOptionResponse]:
    policies = await repository.list_policies(org_id=scope.org_id, db=db)
    return [
        GuardrailPolicyOptionResponse(id=policy.id, name=policy.name, is_active=policy.is_active)
        for policy in policies
    ]


async def create_policy(
    *,
    payload: CreateGuardrailPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailPolicyResponse:
    _validate_rule_matchers(payload.rules)
    async with transaction(db):
        shared_policy = await policy_kernel_repository.create_policy(
            org_id=scope.org_id,
            kind="guardrail",
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            db=db,
        )
        revision = await create_initial_active_revision(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            created_by=actor.id,
            db=db,
        )
        policy = await repository.create_policy(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            name=payload.name,
            description=payload.description,
            enforcement_mode=payload.enforcement_mode,
            is_active=payload.is_active,
            db=db,
        )
        await repository.replace_rules(
            org_id=scope.org_id,
            policy_id=policy.id,
            rules=[rule.model_dump() for rule in payload.rules],
            policy_revision_id=revision.id,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.policy_created",
            message=f"Created guardrail policy {policy.name}.",
            audit_entity_type="guardrail_policy",
            audit_entity_id=policy.id,
            metadata={"policy_id": str(policy.id)},
            db=db,
        )
    rules = await repository.list_policy_rules(org_id=scope.org_id, policy_ids=[policy.id], db=db)
    return await _to_policy_response(policy, rules, scope=scope, db=db)


async def update_policy(
    *,
    policy_id: UUID,
    payload: UpdateGuardrailPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailPolicyResponse:
    if payload.rules is not None:
        _validate_rule_matchers(payload.rules)
    async with transaction(db):
        policy = await repository.get_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
        if policy is None:
            raise GuardrailPolicyNotFoundError
        shared_policy = await _get_shared_guardrail_policy(
            policy=policy,
            scope=scope,
            db=db,
        )
        for field in ("name", "description", "enforcement_mode", "is_active"):
            if field in payload.model_fields_set:
                setattr(policy, field, getattr(payload, field))
        if "name" in payload.model_fields_set:
            shared_policy.name = policy.name
        if "description" in payload.model_fields_set:
            shared_policy.description = policy.description
        if "is_active" in payload.model_fields_set:
            shared_policy.is_active = policy.is_active
        if payload.rules is not None:
            revision = await create_next_active_revision(
                org_id=scope.org_id,
                policy_id=shared_policy.id,
                created_by=actor.id,
                db=db,
            )
            await repository.replace_rules(
                org_id=scope.org_id,
                policy_id=policy.id,
                rules=[rule.model_dump() for rule in payload.rules],
                policy_revision_id=revision.id,
                db=db,
            )
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.policy_updated",
            message=f"Updated guardrail policy {policy.name}.",
            audit_entity_type="guardrail_policy",
            audit_entity_id=policy.id,
            metadata={"policy_id": str(policy.id)},
            db=db,
        )
    rules = await repository.list_policy_rules(org_id=scope.org_id, policy_ids=[policy.id], db=db)
    return await _to_policy_response(policy, rules, scope=scope, db=db)


async def _get_shared_guardrail_policy(
    *,
    policy,
    scope: Scope,
    db: AsyncSession,
) -> Policy:
    shared_policy = await policy_kernel_repository.get_policy(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db,
    )
    if shared_policy is None or shared_policy.kind != "guardrail":
        raise RuntimeError("guardrail policy is missing its shared policy row")
    return shared_policy


async def _create_guardrail_assignment(
    *,
    org_id: UUID,
    shared_policy_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    mode: str,
    is_active: bool,
    db: AsyncSession,
) -> PolicyAssignment:
    now = datetime.now(UTC)
    return await policy_kernel_repository.create_policy_assignment(
        org_id=org_id,
        values={
            "policy_id": shared_policy_id,
            "policy_type": "guardrail",
            "scope_type": scope_type,
            "team_id": team_id,
            "project_id": project_id,
            "virtual_key_id": virtual_key_id,
            "scope_target_key": assignment_scope_target_key(
                scope_type=scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
            ),
            "mode": mode,
            "effective_from": now,
            "effective_to": None if is_active else now,
            "is_active": is_active,
        },
        db=db,
    )


async def _replace_guardrail_assignment(
    *,
    org_id: UUID,
    previous_assignment_id: UUID | None,
    shared_policy_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    mode: str,
    is_active: bool,
    db: AsyncSession,
) -> PolicyAssignment | None:
    now = datetime.now(UTC)
    previous_assignment = None
    if previous_assignment_id is not None:
        previous_assignment = await policy_kernel_repository.get_policy_assignment(
            assignment_id=previous_assignment_id,
            org_id=org_id,
            db=db,
        )
        if previous_assignment is not None and previous_assignment.effective_to is None:
            if not is_active:
                previous_assignment.policy_id = shared_policy_id
                previous_assignment.scope_type = scope_type
                previous_assignment.team_id = team_id
                previous_assignment.project_id = project_id
                previous_assignment.virtual_key_id = virtual_key_id
                previous_assignment.scope_target_key = assignment_scope_target_key(
                    scope_type=scope_type,
                    team_id=team_id,
                    project_id=project_id,
                    virtual_key_id=virtual_key_id,
                )
                previous_assignment.mode = mode
            previous_assignment.effective_to = now
            previous_assignment.is_active = False
    if not is_active:
        await db.flush()
        return previous_assignment
    replacement = await _create_guardrail_assignment(
        org_id=org_id,
        shared_policy_id=shared_policy_id,
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        mode=mode,
        is_active=True,
        db=db,
    )
    if previous_assignment is not None:
        previous_assignment.superseded_by_assignment_id = replacement.id
    await db.flush()
    return replacement


async def _close_guardrail_assignment(
    *,
    org_id: UUID,
    assignment_id: UUID,
    db: AsyncSession,
) -> None:
    assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment_id,
        org_id=org_id,
        db=db,
    )
    if assignment is None or assignment.effective_to is not None:
        return
    assignment.effective_to = datetime.now(UTC)
    assignment.is_active = False
    await db.flush()


async def _close_guardrail_policy_assignments(
    *,
    org_id: UUID,
    policy_id: UUID,
    db: AsyncSession,
) -> None:
    assignments = await repository.list_policy_assignments(
        org_id=org_id,
        policy_id=policy_id,
        active_only=True,
        db=db,
    )
    for assignment in assignments:
        await _close_guardrail_assignment(
            org_id=org_id,
            assignment_id=assignment.id,
            db=db,
        )


async def delete_policy(
    *,
    policy_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        policy = await repository.get_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
        if policy is None:
            raise GuardrailPolicyNotFoundError
        await _close_guardrail_policy_assignments(
            org_id=scope.org_id,
            policy_id=policy.id,
            db=db,
        )
        shared_policy = await _get_shared_guardrail_policy(policy=policy, scope=scope, db=db)
        shared_policy.is_active = False
        policy.is_active = False
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.policy_deleted",
            message=f"Deleted guardrail policy {policy.name}.",
            audit_entity_type="guardrail_policy",
            audit_entity_id=policy_id,
            metadata={"policy_id": str(policy_id)},
            db=db,
        )


async def get_policy_impact(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> GuardrailImpactResponse:
    policy = await repository.get_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise GuardrailPolicyNotFoundError
    assignments = await repository.list_policy_assignments(
        org_id=scope.org_id,
        policy_id=policy_id,
        active_only=True,
        db=db,
    )
    if actor is not None and not _has_global_guardrail_visibility(actor):
        visible_ids = {
            assignment.id
            for assignment in await _visible_assignments(actor=actor, scope=scope, db=db)
        }
        assignments = [assignment for assignment in assignments if assignment.id in visible_ids]
        if not assignments:
            raise GuardrailPolicyNotFoundError
    return await _impact_from_assignments(org_id=scope.org_id, assignments=assignments, db=db)


async def list_assignments(
    *,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> list[GuardrailAssignmentResponse]:
    assignments = await _visible_assignments(actor=actor, scope=scope, db=db)
    return [_to_assignment_response(item) for item in assignments]


async def create_assignment(
    *,
    payload: CreateGuardrailAssignmentRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailAssignmentResponse:
    async with transaction(db):
        policy = await repository.get_policy(
            policy_id=payload.policy_id,
            org_id=scope.org_id,
            db=db,
        )
        if policy is None:
            raise GuardrailPolicyNotFoundError
        team_id, project_id, virtual_key_id = await _validate_assignment_target(
            org_id=scope.org_id,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            db=db,
        )
        existing = await repository.find_assignment_for_scope(
            org_id=scope.org_id,
            policy_id=payload.policy_id,
            scope_type=payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
        if existing is not None:
            raise GuardrailAssignmentConflictError
        shared_policy = await _get_shared_guardrail_policy(
            policy=policy,
            scope=scope,
            db=db,
        )
        assignment = await _create_guardrail_assignment(
            org_id=scope.org_id,
            shared_policy_id=shared_policy.id,
            scope_type=payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            mode=payload.enforcement_mode,
            is_active=payload.is_active,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.assignment_created",
            message=f"Assigned guardrail policy {policy.name}.",
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            audit_entity_type="guardrail_assignment",
            audit_entity_id=assignment.id,
            metadata={
                "assignment_id": str(assignment.id),
                "policy_id": str(policy.id),
                "scope_type": payload.scope_type,
            },
            db=db,
        )
    created = await repository.get_assignment(
        assignment_id=assignment.id,
        org_id=scope.org_id,
        db=db,
    )
    if created is None:
        raise GuardrailAssignmentNotFoundError
    return _to_assignment_response(created)


async def update_assignment(
    *,
    assignment_id: UUID,
    payload: UpdateGuardrailAssignmentRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailAssignmentResponse:
    async with transaction(db):
        assignment = await repository.get_assignment(
            assignment_id=assignment_id,
            org_id=scope.org_id,
            db=db,
        )
        if assignment is None:
            raise GuardrailAssignmentNotFoundError
        policy_id = payload.policy_id if payload.policy_id is not None else assignment.policy_id
        policy = await repository.get_policy(
            policy_id=policy_id,
            org_id=scope.org_id,
            db=db,
        )
        if policy is None:
            raise GuardrailPolicyNotFoundError
        scope_type = payload.scope_type if payload.scope_type is not None else assignment.scope_type
        team_id, project_id, virtual_key_id = _assignment_scope_ids(
            scope_type=scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            fallback=assignment,
        )
        team_id, project_id, virtual_key_id = await _validate_assignment_target(
            org_id=scope.org_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
        existing = await repository.find_assignment_for_scope(
            org_id=scope.org_id,
            policy_id=policy_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
        if existing is not None and existing.id != assignment.id:
            raise GuardrailAssignmentConflictError
        shared_policy = await _get_shared_guardrail_policy(
            policy=policy,
            scope=scope,
            db=db,
        )
        enforcement_mode = payload.enforcement_mode or assignment.enforcement_mode
        is_active = payload.is_active if payload.is_active is not None else assignment.is_active
        replacement = await _replace_guardrail_assignment(
            org_id=scope.org_id,
            previous_assignment_id=assignment.id,
            shared_policy_id=shared_policy.id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            mode=enforcement_mode,
            is_active=is_active,
            db=db,
        )
        if replacement is None:
            raise GuardrailAssignmentNotFoundError
        assignment_id = replacement.id
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.assignment_updated",
            message="Updated guardrail assignment.",
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            audit_entity_type="guardrail_assignment",
            audit_entity_id=assignment_id,
            metadata={"assignment_id": str(assignment_id)},
            db=db,
        )
    updated = await repository.get_assignment(
        assignment_id=assignment_id,
        org_id=scope.org_id,
        db=db,
    )
    if updated is None:
        raise GuardrailAssignmentNotFoundError
    return _to_assignment_response(updated)


async def delete_assignment(
    *,
    assignment_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        assignment = await repository.get_assignment(
            assignment_id=assignment_id,
            org_id=scope.org_id,
            db=db,
        )
        if assignment is None:
            raise GuardrailAssignmentNotFoundError
        await _close_guardrail_assignment(
            org_id=scope.org_id,
            assignment_id=assignment.id,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.assignment_deleted",
            message="Deleted guardrail assignment.",
            team_id=assignment.team_id,
            project_id=assignment.project_id,
            virtual_key_id=assignment.virtual_key_id,
            audit_entity_type="guardrail_assignment",
            audit_entity_id=assignment_id,
            metadata={"assignment_id": str(assignment_id)},
            db=db,
        )


async def get_assignment_impact(
    *,
    assignment_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> GuardrailImpactResponse:
    assignment = await repository.get_assignment(
        assignment_id=assignment_id,
        org_id=scope.org_id,
        db=db,
    )
    if assignment is None:
        raise GuardrailAssignmentNotFoundError
    if actor is not None and not _has_global_guardrail_visibility(actor):
        visible_ids = {
            item.id for item in await _visible_assignments(actor=actor, scope=scope, db=db)
        }
        if assignment.id not in visible_ids:
            raise GuardrailAssignmentNotFoundError
    return await _impact_from_assignments(
        org_id=scope.org_id,
        assignments=[assignment] if assignment.is_active else [],
        db=db,
    )


async def evaluate_request(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> GuardrailEvaluationResult:
    return await _evaluate_context(context=context, db=db)


async def evaluate_response(
    *,
    context: GuardrailEvaluationContext,
    response_text: str,
    db: AsyncSession,
) -> GuardrailEvaluationResult:
    return await _evaluate_context(
        context=context.model_copy(update={"phase": "response", "response_text": response_text}),
        db=db,
    )


async def evaluate_context_readonly(
    *,
    context: GuardrailEvaluationContext,
    detector_mode: str,
    db: AsyncSession,
) -> list[GuardrailReadonlyEvaluation]:
    runtime_rules = await runtime_rules_for_context_readonly(
        context=context,
        db=db,
    )
    return await evaluate_guardrail_rules_readonly(
        context=context,
        rules=runtime_rules,
        detector_mode=detector_mode,
        db=db,
    )


async def runtime_rules_for_context_readonly(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> list[RuntimeGuardrailRuleInput]:
    assignments = await repository.list_effective_assignments(
        org_id=context.org_id,
        team_id=context.team_id,
        project_id=context.project_id,
        virtual_key_id=context.virtual_key_id,
        db=db,
    )
    if not assignments:
        return []
    policies = {
        policy.id: policy
        for policy in await repository.list_policies(org_id=context.org_id, db=db)
        if policy.is_active
    }
    policy_ids = [
        assignment.policy_id for assignment in assignments if assignment.policy_id in policies
    ]
    rules = await repository.list_policy_rules(org_id=context.org_id, policy_ids=policy_ids, db=db)
    assignments_by_policy: dict[UUID, list[GuardrailAssignmentView]] = {}
    for assignment in assignments:
        assignments_by_policy.setdefault(assignment.policy_id, []).append(assignment)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    runtime_rules = await _runtime_rules_from_saved_rules(
        rules=rules,
        policies=policies,
        assignments_by_policy=assignments_by_policy,
        policy_mode=policy_mode,
        phase=context.phase,
        db=db,
    )
    return runtime_rules


async def has_enforced_response_guardrails(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> bool:
    assignments = await repository.list_effective_assignments(
        org_id=context.org_id,
        team_id=context.team_id,
        project_id=context.project_id,
        virtual_key_id=context.virtual_key_id,
        db=db,
    )
    if not assignments:
        return False
    policies = {
        policy.id: policy
        for policy in await repository.list_policies(org_id=context.org_id, db=db)
        if policy.is_active
    }
    policy_ids = [
        assignment.policy_id for assignment in assignments if assignment.policy_id in policies
    ]
    rules = await repository.list_policy_rules(org_id=context.org_id, policy_ids=policy_ids, db=db)
    assignments_by_policy: dict[UUID, list[GuardrailAssignmentView]] = {}
    for assignment in assignments:
        assignments_by_policy.setdefault(assignment.policy_id, []).append(assignment)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    return any(
        rule.is_active
        and _rule_applies_to_phase(rule=rule, phase="response")
        and _effective_rule_mode(
            policy_mode=policy_mode.get(rule.policy_id, "enforce"),
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        == "enforce"
        for rule in rules
    )


async def _evaluate_context(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> GuardrailEvaluationResult:
    assignments = await repository.list_effective_assignments(
        org_id=context.org_id,
        team_id=context.team_id,
        project_id=context.project_id,
        virtual_key_id=context.virtual_key_id,
        db=db,
    )
    if not assignments:
        return GuardrailEvaluationResult(evaluated=False, would_deny=[])
    policies = {
        policy.id: policy
        for policy in await repository.list_policies(org_id=context.org_id, db=db)
        if policy.is_active
    }
    policy_ids = [
        assignment.policy_id for assignment in assignments if assignment.policy_id in policies
    ]
    rules = await repository.list_policy_rules(org_id=context.org_id, policy_ids=policy_ids, db=db)
    assignments_by_policy: dict[UUID, list[GuardrailAssignmentView]] = {}
    for assignment in assignments:
        assignments_by_policy.setdefault(assignment.policy_id, []).append(assignment)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    runtime_rules = await _runtime_rules_from_saved_rules(
        rules=rules,
        policies=policies,
        assignments_by_policy=assignments_by_policy,
        policy_mode=policy_mode,
        phase=context.phase,
        db=db,
    )
    evaluations = await evaluate_guardrail_rules_readonly(
        context=context,
        rules=runtime_rules,
        detector_mode="execute_detectors",
        db=db,
    )
    would_deny: list[GuardrailDecisionTrace] = []
    for evaluation in evaluations:
        if not evaluation.denied or evaluation.policy_id is None:
            continue
        mode = "enforce" if evaluation.decision == "blocked" else "dry_run"
        effective_assignment = _effective_rule_assignment(
            mode=mode,
            assignments=assignments_by_policy.get(evaluation.policy_id, []),
        )
        await _record_event(
            context=context,
            policy_id=evaluation.policy_id,
            policy_revision_id=evaluation.policy_revision_id,
            rule_id=evaluation.rule_id,
            decision=evaluation.decision,
            reason=evaluation.reason_code or f"{context.phase}_guardrail_denied",
            metadata=_guardrail_event_metadata(
                evaluation=evaluation,
                runtime_rules=runtime_rules,
                mode=mode,
                phase=context.phase,
            ),
            db=db,
        )
        if mode == "enforce":
            raise GuardrailDeniedError(
                detail=evaluation.message or "Request blocked by guardrail",
                policy_id=evaluation.policy_id,
                policy_revision_id=evaluation.policy_revision_id,
                assignment_id=(effective_assignment.id if effective_assignment else None),
                assignment_mode=mode,
                assignment_scope_type=effective_assignment.scope_type
                if effective_assignment
                else None,
                assignment_team_id=effective_assignment.team_id if effective_assignment else None,
                assignment_project_id=effective_assignment.project_id
                if effective_assignment
                else None,
                assignment_virtual_key_id=effective_assignment.virtual_key_id
                if effective_assignment
                else None,
                rule_id=evaluation.rule_id,
            )
        would_deny.append(
            GuardrailDecisionTrace(
                policy_id=evaluation.policy_id,
                policy_revision_id=evaluation.policy_revision_id,
                assignment_id=(effective_assignment.id if effective_assignment else None),
                assignment_mode=mode,
                assignment_scope_type=effective_assignment.scope_type
                if effective_assignment
                else None,
                assignment_team_id=effective_assignment.team_id if effective_assignment else None,
                assignment_project_id=effective_assignment.project_id
                if effective_assignment
                else None,
                assignment_virtual_key_id=effective_assignment.virtual_key_id
                if effective_assignment
                else None,
                rule_id=evaluation.rule_id,
                reason_code=evaluation.reason_code or f"{context.phase}_guardrail_denied",
                message=evaluation.message,
            )
        )
    await _record_event(
        context=context,
        policy_id=None,
        policy_revision_id=None,
        rule_id=None,
        decision="allowed",
        reason=f"{context.phase}_guardrails_passed",
        metadata={"phase": context.phase},
        db=db,
    )
    return GuardrailEvaluationResult(evaluated=True, would_deny=would_deny)


async def list_events(
    *,
    scope: Scope,
    decision: str | None = None,
    policy_id: UUID | None = None,
    rule_id: UUID | None = None,
    phase: str | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    pool_id: UUID | None = None,
    model: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    limit: int = 50,
    actor: AuthenticatedUser | None = None,
    db: AsyncSession,
) -> list[GuardrailEventResponse]:
    allowed_team_ids: set[UUID] | None = None
    allowed_project_ids: set[UUID] | None = None
    if actor is not None and not _has_global_guardrail_visibility(actor):
        allowed_scopes = authorization_facade.scoped_admin_workspace_ids(actor)
        allowed_team_ids = allowed_scopes.team_ids
        allowed_project_ids = allowed_scopes.project_ids
        if not allowed_team_ids and not allowed_project_ids:
            return []
    events = await repository.list_events(
        org_id=scope.org_id,
        decision=decision,
        phase=phase,
        policy_id=policy_id,
        rule_id=rule_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        pool_id=pool_id,
        model=model,
        before_at=before_at,
        before_id=before_id,
        limit=limit,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    return [_to_event_response(event) for event in events]


async def simulate(
    *,
    payload: GuardrailSimulationRequest,
    scope: Scope,
    actor: AuthenticatedUser | None = None,
    db: AsyncSession,
) -> GuardrailSimulationResponse:
    if payload.policy_id is not None:
        policy = await repository.get_policy(
            policy_id=payload.policy_id,
            org_id=scope.org_id,
            db=db,
        )
        if policy is None:
            raise GuardrailPolicyNotFoundError
        if actor is not None and not _has_global_guardrail_visibility(actor):
            visible_policy_ids = {
                item.id for item in await list_policies(scope=scope, db=db, actor=actor)
            }
            if policy.id not in visible_policy_ids:
                raise GuardrailPolicyNotFoundError
        rules = await repository.list_policy_rules(
            org_id=scope.org_id,
            policy_ids=[policy.id],
            db=db,
        )
        enforcement_mode = policy.enforcement_mode
    else:
        rules = payload.rules or []
        enforcement_mode = payload.enforcement_mode

    context = GuardrailEvaluationContext(
        org_id=scope.org_id,
        team_id=scope.org_id,
        project_id=scope.org_id,
        virtual_key_id=scope.org_id,
        provider_id=payload.provider_id or scope.org_id,
        pool_id=payload.pool_id or scope.org_id,
        provider_model_offering_id=payload.provider_model_offering_id,
        public_model_id=payload.public_model_id,
        public_model_name=payload.public_model_name,
        route_candidate_id=payload.route_candidate_id,
        gateway_endpoint=payload.gateway_endpoint,
        requested_model=payload.requested_model,
        provider_model=payload.provider_model or payload.requested_model,
        prompt_text=payload.prompt_text
        if payload.prompt_text is not None
        else _messages_text(payload.messages),
    )

    runtime_rules = await _runtime_rules_from_simulation_rules(
        rules=rules,
        policy_id=payload.policy_id,
        enforcement_mode=enforcement_mode,
        phase=context.phase,
        db=db,
    )
    evaluations = await evaluate_guardrail_rules_readonly(
        context=context,
        rules=runtime_rules,
        detector_mode="execute_detectors",
        db=db,
    )
    matches: list[GuardrailSimulationMatch] = []
    for evaluation in evaluations:
        if not evaluation.denied:
            continue
        decision = "blocked" if enforcement_mode == "enforce" else "warned"
        matches.append(
            GuardrailSimulationMatch(
                rule_id=evaluation.rule_id,
                rule_type=evaluation.rule_type,
                effect=evaluation.effect,
                priority=_runtime_rule_priority(runtime_rules, evaluation),
                decision=decision,
                reason=evaluation.reason_code or f"{context.phase}_guardrail_denied",
                matched_values=evaluation.matched_values,
            )
        )

    return GuardrailSimulationResponse(
        decision=matches[0].decision if matches else "allowed",
        enforcement_mode=enforcement_mode,
        matches=matches,
    )


async def _runtime_rules_from_saved_rules(
    *,
    rules,
    policies: dict[UUID, object],
    assignments_by_policy: dict[UUID, list[GuardrailAssignmentView]],
    policy_mode: dict[UUID, str],
    phase: str,
    db: AsyncSession,
) -> list[RuntimeGuardrailRuleInput]:
    runtime_rules: list[RuntimeGuardrailRuleInput] = []
    for index, rule in enumerate(rules):
        if not _rule_applies_to_phase(rule=rule, phase=phase):
            continue
        policy = policies.get(rule.policy_id)
        if policy is None:
            continue
        matchers = await repository.list_rule_matchers(
            org_id=rule.org_id,
            rule_id=rule.id,
            db=db,
        )
        mode = _effective_rule_mode(
            policy_mode=policy_mode.get(rule.policy_id, "enforce"),
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        effective_assignment = _effective_rule_assignment(
            mode=mode,
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        runtime_rules.append(
            RuntimeGuardrailRuleInput(
                policy_ref=RuntimeGuardrailPolicyRef(
                    policy_key=f"policy:{rule.policy_id}",
                    policy_id=rule.policy_id,
                    policy_revision_id=rule.policy_revision_id,
                    policy_name=getattr(policy, "name", None),
                    policy_revision_number=None,
                    enforcement_mode=getattr(policy, "enforcement_mode", "enforce"),
                ),
                assignment_refs=[
                    _runtime_assignment_ref(
                        assignment=effective_assignment,
                        assignment_mode=mode,
                    )
                ]
                if effective_assignment
                else [],
                rule_ref=RuntimeGuardrailRuleRef(
                    rule_id=rule.id,
                    rule_name=None,
                    rule_index=index,
                ),
                phase=phase,
                source_phase=getattr(rule, "phase", phase),
                rule_type=rule.rule_type,
                effect=rule.effect,
                values=rule.values,
                config=rule.config or {},
                matchers=[
                    RuntimeMatcherInput(
                        dimension=matcher.dimension,
                        operator=matcher.operator,
                        value_json=matcher.value_json,
                    )
                    for matcher in matchers
                ],
                priority=rule.priority,
                is_active=rule.is_active,
                source_created_at=rule.created_at,
            )
        )
    return runtime_rules


async def _runtime_rules_from_simulation_rules(
    *,
    rules,
    policy_id: UUID | None,
    enforcement_mode: str,
    phase: str,
    db: AsyncSession,
) -> list[RuntimeGuardrailRuleInput]:
    runtime_rules: list[RuntimeGuardrailRuleInput] = []
    for index, rule in enumerate(rules):
        if not _rule_applies_to_phase(rule=rule, phase=phase):
            continue
        rule_id = getattr(rule, "id", None)
        if rule_id is not None:
            matchers = await repository.list_rule_matchers(
                org_id=rule.org_id,
                rule_id=rule_id,
                db=db,
            )
        else:
            matchers = getattr(rule, "matchers", [])
        runtime_rules.append(
            RuntimeGuardrailRuleInput(
                policy_ref=RuntimeGuardrailPolicyRef(
                    policy_key=f"policy:{policy_id}" if policy_id else "draft:guardrail_policy",
                    policy_id=policy_id,
                    policy_revision_id=getattr(rule, "policy_revision_id", None),
                    policy_name=None,
                    policy_revision_number=None,
                    enforcement_mode=enforcement_mode,
                    draft_ref=None if policy_id else "draft:guardrail_policy",
                ),
                assignment_refs=[],
                rule_ref=RuntimeGuardrailRuleRef(
                    rule_id=rule_id,
                    rule_name=None,
                    rule_index=index,
                    draft_ref=None if rule_id else f"draft:guardrail_policy.rules[{index}]",
                ),
                phase=phase,
                source_phase=getattr(rule, "phase", phase),
                rule_type=rule.rule_type,
                effect=rule.effect,
                values=rule.values,
                config=getattr(rule, "config", {}) or {},
                matchers=[
                    RuntimeMatcherInput(
                        dimension=matcher.dimension,
                        operator=matcher.operator,
                        value_json=matcher.value_json,
                    )
                    for matcher in matchers
                ],
                priority=rule.priority,
                is_active=getattr(rule, "is_active", True),
                source_created_at=getattr(rule, "created_at", None),
            )
        )
    return runtime_rules


def _runtime_assignment_ref(
    *,
    assignment: GuardrailAssignmentView,
    assignment_mode: str,
) -> RuntimeGuardrailAssignmentRef:
    return RuntimeGuardrailAssignmentRef(
        assignment_id=assignment.id,
        assignment_mode=assignment_mode,
        assignment_scope_type=assignment.scope_type,
        assignment_scope_label=assignment.scope_type,
    )


def _runtime_rule_priority(
    rules: list[RuntimeGuardrailRuleInput],
    evaluation: GuardrailReadonlyEvaluation,
) -> int:
    for rule in rules:
        if rule.rule_ref.rule_id == evaluation.rule_id and rule.rule_type == evaluation.rule_type:
            return rule.priority
    return 100


def _rule_applies_to_phase(*, rule, phase: str) -> bool:
    rule_phase = getattr(rule, "phase", "both")
    return rule_phase in {"both", phase}


def _guardrail_event_metadata(
    *,
    evaluation: GuardrailReadonlyEvaluation,
    runtime_rules: list[RuntimeGuardrailRuleInput],
    mode: str,
    phase: str,
) -> dict:
    metadata = {
        "enforcement_mode": mode,
        "phase": phase,
    }
    if evaluation.effect == "allow":
        metadata["allowed_values"] = _runtime_rule_values(runtime_rules, evaluation)
    else:
        metadata["allowed_values"] = []
    if evaluation.rule_type == "pii":
        metadata["pii_types"] = evaluation.matched_values
        metadata["matched_values_redacted"] = True
    else:
        metadata["matched_values"] = evaluation.matched_values
    return metadata


def _runtime_rule_values(
    rules: list[RuntimeGuardrailRuleInput],
    evaluation: GuardrailReadonlyEvaluation,
) -> list[str]:
    for rule in rules:
        if rule.rule_ref.rule_id == evaluation.rule_id and rule.rule_type == evaluation.rule_type:
            return rule.values
    return []


@sqlite_write_unit
async def _record_event(
    *,
    context: GuardrailEvaluationContext,
    policy_id: UUID | None,
    policy_revision_id: UUID | None,
    rule_id: UUID | None,
    decision: str,
    reason: str,
    metadata: dict,
    db: AsyncSession,
) -> None:
    await repository.create_event(
        org_id=context.org_id,
        policy_id=policy_id,
        policy_revision_id=policy_revision_id,
        rule_id=rule_id,
        decision=decision,
        phase=context.phase,
        reason=reason,
        team_id=context.team_id,
        project_id=context.project_id,
        virtual_key_id=context.virtual_key_id,
        provider_id=context.provider_id,
        pool_id=context.pool_id,
        request_id=context.request_id,
        gateway_request_id=context.gateway_request_id,
        route_attempt_id=context.route_attempt_id,
        requested_model=context.requested_model,
        provider_model=context.provider_model,
        metadata=metadata,
        db=db,
    )
    await db.commit()


def _messages_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


def _content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_content_to_text(part) for part in content)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return str(content)


def _rules_by_policy(rules) -> dict[UUID, list]:
    grouped: dict[UUID, list] = {}
    for rule in rules:
        grouped.setdefault(rule.policy_id, []).append(rule)
    return grouped


def _assignment_scope_ids(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    fallback: GuardrailAssignmentView,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if scope_type == "team":
        return team_id or fallback.team_id, None, None
    if scope_type == "project":
        return None, project_id or fallback.project_id, None
    if scope_type == "virtual_key":
        return None, None, virtual_key_id or fallback.virtual_key_id
    return None, None, None


def _effective_rule_mode(*, policy_mode: str, assignments: list[GuardrailAssignmentView]) -> str:
    if policy_mode == "monitor":
        return "dry_run"
    if any(assignment.enforcement_mode == "enforce" for assignment in assignments):
        return "enforce"
    return "dry_run"


def _effective_rule_assignment(
    *,
    mode: str,
    assignments: list[GuardrailAssignmentView],
) -> GuardrailAssignmentView | None:
    if not assignments:
        return None
    candidates = (
        [assignment for assignment in assignments if assignment.enforcement_mode == "enforce"]
        if mode == "enforce"
        else assignments
    )
    return max(candidates, key=lambda assignment: _assignment_specificity(assignment.scope_type))


def _assignment_specificity(scope_type: str) -> int:
    return assignment_scope_specificity(scope_type)


async def _validate_assignment_target(
    *,
    org_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    try:
        validated = await workspace_facade.validate_assignment_scope(
            organization_id=org_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
    except WorkspaceScopeNotFoundError as exc:
        raise GuardrailAssignmentTargetNotFoundError from exc
    return validated.team_id, validated.project_id, validated.virtual_key_id


def _has_global_guardrail_visibility(actor: AuthenticatedUser) -> bool:
    return authorization_facade.has_any_permission(
        actor,
        {Permissions.GUARDRAILS_VIEW, Permissions.GUARDRAILS_MANAGE},
    )


async def _visible_assignments(
    *,
    actor: AuthenticatedUser | None,
    scope: Scope,
    db: AsyncSession,
) -> list[GuardrailAssignmentView]:
    assignments = await repository.list_assignments(org_id=scope.org_id, db=db)
    if actor is None or _has_global_guardrail_visibility(actor):
        return assignments

    visible: list[GuardrailAssignmentView] = []
    for assignment in assignments:
        decision = await authorization_facade.can(
            actor=actor,
            permission=Permissions.GUARDRAILS_VIEW,
            target=AuthorizationTarget.workspace_scope(
                scope_type=assignment.scope_type,
                team_id=assignment.team_id,
                project_id=assignment.project_id,
                virtual_key_id=assignment.virtual_key_id,
            ),
            scope=scope,
            db=db,
        )
        if decision.allowed:
            visible.append(assignment)
    return visible


async def _impact_from_assignments(
    *, org_id: UUID, assignments: list[GuardrailAssignmentView], db: AsyncSession
) -> GuardrailImpactResponse:
    teams: dict[UUID, GuardrailImpactTarget] = {}
    projects: dict[UUID, GuardrailImpactTarget] = {}
    scope = Scope(org_id=org_id)
    project_models = await _affected_projects(org_id=org_id, assignments=assignments, db=db)
    for project in project_models:
        projects[project.id] = GuardrailImpactTarget(id=project.id, name=project.name)
    keys = await workspace_facade.list_workspace_virtual_keys(
        scope=scope,
        project_ids={project.id for project in project_models},
        db=db,
    )
    virtual_keys = {
        key.id: GuardrailImpactVirtualKey(
            id=key.id,
            name=key.name,
            project_id=key.project_id,
            project_name=key.project_name,
        )
        for key in keys
    }
    for assignment in assignments:
        if assignment.scope_type == "team" and assignment.team_id is not None:
            labels = await workspace_facade.get_workspace_label_maps(
                scope=scope,
                team_ids={assignment.team_id},
                project_ids=set(),
                virtual_key_ids=set(),
                db=db,
            )
            if assignment.team_id in labels.teams:
                teams[assignment.team_id] = GuardrailImpactTarget(
                    id=assignment.team_id,
                    name=labels.teams[assignment.team_id],
                )
        elif assignment.scope_type == "virtual_key" and assignment.virtual_key_id is not None:
            key_options = await workspace_facade.list_workspace_virtual_keys(
                scope=scope,
                virtual_key_ids={assignment.virtual_key_id},
                usable_only=False,
                db=db,
            )
            for key in key_options:
                virtual_keys[key.id] = GuardrailImpactVirtualKey(**key.__dict__)
                projects[key.project_id] = GuardrailImpactTarget(
                    id=key.project_id,
                    name=key.project_name,
                )
    return GuardrailImpactResponse(
        affected_teams=list(teams.values()),
        affected_projects=list(projects.values()),
        affected_virtual_keys=list(virtual_keys.values()),
        affected_team_count=len(teams),
        affected_project_count=len(projects),
        affected_virtual_key_count=len(virtual_keys),
    )


async def _affected_projects(
    *, org_id: UUID, assignments: list[GuardrailAssignmentView], db: AsyncSession
) -> list:
    project_ids = [item.project_id for item in assignments if item.project_id is not None]
    team_ids = {item.team_id for item in assignments if item.team_id is not None}
    projects = []
    if any(item.scope_type == "org" for item in assignments):
        projects.extend(
            await workspace_facade.list_workspace_projects(
                scope=Scope(org_id=org_id),
                include_all=True,
                db=db,
            )
        )
    if team_ids:
        projects.extend(
            await workspace_facade.list_workspace_projects(
                scope=Scope(org_id=org_id),
                team_ids=team_ids,
                db=db,
            )
        )
    projects.extend(
        await workspace_facade.list_workspace_projects(
            scope=Scope(org_id=org_id),
            project_ids=set(project_ids),
            db=db,
        )
    )
    return list({project.id: project for project in projects}.values())


async def _to_policy_response(
    policy,
    rules,
    *,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailPolicyResponse:
    rule_responses = []
    for rule in rules:
        response = GuardrailRuleResponse.model_validate(rule)
        response.matchers = [
            GuardrailRuleMatcherResponse.model_validate(matcher)
            for matcher in await repository.list_rule_matchers(
                org_id=scope.org_id,
                rule_id=rule.id,
                db=db,
            )
        ]
        rule_responses.append(response)
    return GuardrailPolicyResponse(
        id=policy.id,
        org_id=policy.org_id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        enforcement_mode=policy.enforcement_mode,
        is_active=policy.is_active,
        rules=rule_responses,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _validate_rule_matchers(rules) -> None:
    validate_guardrail_rule_payload(rules)


def _to_assignment_response(
    assignment: GuardrailAssignmentView,
) -> GuardrailAssignmentResponse:
    return GuardrailAssignmentResponse(
        id=assignment.id,
        org_id=assignment.org_id,
        policy_id=assignment.policy_id,
        policy_name=assignment.policy_name,
        scope_type=assignment.scope_type,
        team_id=assignment.team_id,
        project_id=assignment.project_id,
        virtual_key_id=assignment.virtual_key_id,
        enforcement_mode=assignment.enforcement_mode,
        is_active=assignment.is_active,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _to_event_response(event: GuardrailEvent) -> GuardrailEventResponse:
    return GuardrailEventResponse(
        id=event.id,
        org_id=event.org_id,
        policy_id=event.policy_id,
        policy_revision_id=event.policy_revision_id,
        rule_id=event.rule_id,
        decision=event.decision,
        phase=event.phase,
        reason=event.reason,
        team_id=event.team_id,
        project_id=event.project_id,
        virtual_key_id=event.virtual_key_id,
        provider_id=event.provider_id,
        pool_id=event.pool_id,
        request_id=event.request_id,
        gateway_request_id=event.gateway_request_id,
        route_attempt_id=event.route_attempt_id,
        requested_model=event.requested_model,
        provider_model=event.provider_model,
        metadata=event.metadata_,
        created_at=event.created_at,
    )
