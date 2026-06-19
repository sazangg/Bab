import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails.detectors.registry import DEFAULT_PII_DETECTOR, get_detector
from app.modules.guardrails.errors import (
    GuardrailAssignmentConflictError,
    GuardrailAssignmentNotFoundError,
    GuardrailAssignmentTargetNotFoundError,
    GuardrailDeniedError,
    GuardrailPolicyNotFoundError,
)
from app.modules.guardrails.internal import repository
from app.modules.guardrails.internal.models import GuardrailAssignment, GuardrailEvent
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
from app.modules.policies.dimensions import (
    PolicyDimensionStage,
    evaluate_matcher,
    validate_matcher,
)
from app.modules.policies.errors import PolicyValidationError
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.internal.models import PolicyRevision


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
    if actor is not None and not _is_org_guardrail_viewer(actor):
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
    async with transaction(db):
        shared_policy = await policies_repository.create_policy(
            org_id=scope.org_id,
            kind="guardrail",
            name=payload.name,
            description=payload.description,
            db=db,
        )
        shared_policy.is_active = payload.is_active
        revision = await policies_repository.create_policy_revision(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            revision_number=1,
            status="active",
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
        _validate_rule_matchers(payload.rules)
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
    async with transaction(db):
        policy = await repository.get_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
        if policy is None:
            raise GuardrailPolicyNotFoundError
        shared_policy = await _ensure_shared_guardrail_policy(
            policy=policy,
            actor=actor,
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
            _validate_rule_matchers(payload.rules)
            revision = await _create_next_active_guardrail_revision(
                org_id=scope.org_id,
                shared_policy_id=shared_policy.id,
                actor_id=actor.id,
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


async def _ensure_shared_guardrail_policy(
    *,
    policy,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
):
    if policy.policy_id is not None:
        shared_policy = await policies_repository.get_policy(
            org_id=scope.org_id,
            policy_id=policy.policy_id,
            db=db,
        )
        if shared_policy is not None:
            return shared_policy
    legacy_rules = await repository.list_policy_rules(
        org_id=scope.org_id,
        policy_ids=[policy.id],
        db=db,
    )
    shared_policy = await policies_repository.create_policy(
        org_id=scope.org_id,
        kind="guardrail",
        name=policy.name,
        description=policy.description,
        db=db,
    )
    shared_policy.is_active = policy.is_active
    policy.policy_id = shared_policy.id
    revision = await policies_repository.create_policy_revision(
        org_id=scope.org_id,
        policy_id=shared_policy.id,
        revision_number=1,
        status="active",
        created_by=actor.id,
        db=db,
    )
    await repository.replace_rules(
        org_id=scope.org_id,
        policy_id=policy.id,
        rules=[
            {
                "rule_type": rule.rule_type,
                "effect": rule.effect,
                "phase": rule.phase,
                "values": rule.values,
                "config": rule.config,
                "priority": rule.priority,
                "is_active": rule.is_active,
            }
            for rule in legacy_rules
        ],
        policy_revision_id=revision.id,
        db=db,
    )
    return shared_policy


async def _create_next_active_guardrail_revision(
    *,
    org_id: UUID,
    shared_policy_id: UUID,
    actor_id: UUID,
    db: AsyncSession,
) -> PolicyRevision:
    active_revision = await policies_repository.archive_active_policy_revision(
        org_id=org_id,
        policy_id=shared_policy_id,
        db=db,
    )
    next_revision_number = 1 if active_revision is None else active_revision.revision_number + 1
    return await policies_repository.create_policy_revision(
        org_id=org_id,
        policy_id=shared_policy_id,
        revision_number=next_revision_number,
        status="active",
        created_by=actor_id,
        db=db,
    )


async def _create_shared_guardrail_assignment(
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
):
    now = datetime.now(UTC)
    return await policies_repository.create_policy_assignment(
        org_id=org_id,
        values={
            "policy_id": shared_policy_id,
            "policy_type": "guardrail",
            "scope_type": scope_type,
            "team_id": team_id,
            "project_id": project_id,
            "virtual_key_id": virtual_key_id,
            "scope_target_key": policies_repository.policy_assignment_scope_target_key(
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


async def _replace_shared_guardrail_assignment(
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
) -> UUID | None:
    now = datetime.now(UTC)
    previous_assignment = None
    if previous_assignment_id is not None:
        previous_assignment = await policies_repository.get_policy_assignment(
            assignment_id=previous_assignment_id,
            org_id=org_id,
            db=db,
        )
        if previous_assignment is not None and previous_assignment.effective_to is None:
            previous_assignment.effective_to = now
            previous_assignment.is_active = False
    if not is_active:
        await db.flush()
        return previous_assignment_id
    replacement = await _create_shared_guardrail_assignment(
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
    return replacement.id


async def _close_shared_guardrail_assignment(
    *,
    org_id: UUID,
    assignment_id: UUID | None,
    db: AsyncSession,
) -> None:
    if assignment_id is None:
        return
    assignment = await policies_repository.get_policy_assignment(
        assignment_id=assignment_id,
        org_id=org_id,
        db=db,
    )
    if assignment is None or assignment.effective_to is not None:
        return
    assignment.effective_to = datetime.now(UTC)
    assignment.is_active = False
    await db.flush()


async def _close_shared_guardrail_assignments_for_policy(
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
        await _close_shared_guardrail_assignment(
            org_id=org_id,
            assignment_id=assignment.policy_assignment_id,
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
        await _close_shared_guardrail_assignments_for_policy(
            org_id=scope.org_id,
            policy_id=policy.id,
            db=db,
        )
        if policy.policy_id is not None:
            shared_policy = await policies_repository.get_policy(
                org_id=scope.org_id,
                policy_id=policy.policy_id,
                db=db,
            )
            if shared_policy is not None:
                shared_policy.is_active = False
        await repository.delete_policy(policy=policy, db=db)
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
    if actor is not None and not _is_org_guardrail_viewer(actor):
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
    policies = await repository.list_policies(org_id=scope.org_id, db=db)
    policy_names = {policy.id: policy.name for policy in policies}
    return [
        _to_assignment_response(item, policy_names.get(item.policy_id, "Unknown policy"))
        for item in assignments
    ]


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
        await _validate_assignment_target(
            org_id=scope.org_id,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            db=db,
        )
        team_id, project_id, virtual_key_id = _assignment_scope_ids_from_payload(
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
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
        shared_policy = await _ensure_shared_guardrail_policy(
            policy=policy,
            actor=actor,
            scope=scope,
            db=db,
        )
        shared_assignment = await _create_shared_guardrail_assignment(
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
        assignment = await repository.create_assignment(
            org_id=scope.org_id,
            policy_id=payload.policy_id,
            scope_type=payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            enforcement_mode=payload.enforcement_mode,
            is_active=payload.is_active,
            policy_assignment_id=shared_assignment.id,
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
    return _to_assignment_response(assignment, policy.name)


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
        await _validate_assignment_target(
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
        shared_policy = await _ensure_shared_guardrail_policy(
            policy=policy,
            actor=actor,
            scope=scope,
            db=db,
        )
        assignment.policy_id = policy_id
        assignment.scope_type = scope_type
        assignment.team_id = team_id
        assignment.project_id = project_id
        assignment.virtual_key_id = virtual_key_id
        if payload.enforcement_mode is not None:
            assignment.enforcement_mode = payload.enforcement_mode
        if payload.is_active is not None:
            assignment.is_active = payload.is_active
        assignment.policy_assignment_id = await _replace_shared_guardrail_assignment(
            org_id=scope.org_id,
            previous_assignment_id=assignment.policy_assignment_id,
            shared_policy_id=shared_policy.id,
            scope_type=assignment.scope_type,
            team_id=assignment.team_id,
            project_id=assignment.project_id,
            virtual_key_id=assignment.virtual_key_id,
            mode=assignment.enforcement_mode,
            is_active=assignment.is_active,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="guardrail",
            action="guardrail.assignment_updated",
            message="Updated guardrail assignment.",
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            audit_entity_type="guardrail_assignment",
            audit_entity_id=assignment.id,
            metadata={"assignment_id": str(assignment.id)},
            db=db,
        )
    return _to_assignment_response(assignment, policy.name if policy else "Unknown policy")


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
        await _close_shared_guardrail_assignment(
            org_id=scope.org_id,
            assignment_id=assignment.policy_assignment_id,
            db=db,
        )
        await repository.delete_assignment(assignment=assignment, db=db)
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
    if actor is not None and not _is_org_guardrail_viewer(actor):
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
    assignments_by_policy: dict[UUID, list[GuardrailAssignment]] = {}
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
    assignments_by_policy: dict[UUID, list[GuardrailAssignment]] = {}
    for assignment in assignments:
        assignments_by_policy.setdefault(assignment.policy_id, []).append(assignment)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    would_deny: list[GuardrailDecisionTrace] = []
    for rule in rules:
        if (
            not rule.is_active
            or not _rule_applies_to_phase(rule=rule, phase=context.phase)
            or not await _rule_matchers_apply(rule=rule, context=context, db=db)
        ):
            continue
        evaluation = await _evaluate_rule(rule=rule, context=context)
        if not evaluation["denied"]:
            continue
        mode = _effective_rule_mode(
            policy_mode=policy_mode.get(rule.policy_id, "enforce"),
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        effective_assignment = _effective_rule_assignment(
            mode=mode,
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        reason = _rule_denial_reason(rule)
        rule_label = "allowlist" if rule.effect == "allow" else rule.rule_type
        message = f"{context.phase} blocked by guardrail {rule_label} rule"
        await _record_event(
            context=context,
            policy_id=rule.policy_id,
            policy_revision_id=rule.policy_revision_id,
            rule_id=rule.id,
            decision="blocked" if mode == "enforce" else "would_block",
            reason=reason,
            metadata=_guardrail_event_metadata(
                rule=rule,
                evaluation=evaluation,
                mode=mode,
                phase=context.phase,
            ),
            db=db,
        )
        if mode == "enforce":
            raise GuardrailDeniedError(
                detail=message,
                policy_id=rule.policy_id,
                policy_revision_id=rule.policy_revision_id,
                assignment_id=(
                    effective_assignment.policy_assignment_id or effective_assignment.id
                    if effective_assignment
                    else None
                ),
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
                rule_id=rule.id,
            )
        would_deny.append(
            GuardrailDecisionTrace(
                policy_id=rule.policy_id,
                policy_revision_id=rule.policy_revision_id,
                assignment_id=(
                    effective_assignment.policy_assignment_id or effective_assignment.id
                    if effective_assignment
                    else None
                ),
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
                rule_id=rule.id,
                reason_code=reason,
                message=message,
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
    limit: int = 50,
    actor: AuthenticatedUser | None = None,
    db: AsyncSession,
) -> list[GuardrailEventResponse]:
    allowed_team_ids: set[UUID] | None = None
    allowed_project_ids: set[UUID] | None = None
    if actor is not None and not _is_org_guardrail_viewer(actor):
        allowed_team_ids, allowed_project_ids = _managed_scope_ids(actor)
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
        if actor is not None and not _is_org_guardrail_viewer(actor):
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

    matches: list[GuardrailSimulationMatch] = []
    for rule in rules:
        is_active = getattr(rule, "is_active", True)
        if not is_active:
            continue
        if not _rule_applies_to_phase(rule=rule, phase=context.phase):
            continue
        if not await _rule_matchers_apply(rule=rule, context=context, db=db):
            continue
        evaluation = await _evaluate_rule(rule=rule, context=context)
        if not evaluation["denied"]:
            continue
        decision = "blocked" if enforcement_mode == "enforce" else "warned"
        matches.append(
            GuardrailSimulationMatch(
                rule_id=getattr(rule, "id", None),
                rule_type=rule.rule_type,
                effect=rule.effect,
                priority=rule.priority,
                decision=decision,
                reason=_rule_denial_reason(rule),
                matched_values=evaluation["matched_values"],
            )
        )

    return GuardrailSimulationResponse(
        decision=matches[0].decision if matches else "allowed",
        enforcement_mode=enforcement_mode,
        matches=matches,
    )


async def _evaluate_rule(*, rule, context: GuardrailEvaluationContext) -> dict:
    matched_values = await _matched_rule_values(rule=rule, context=context)
    matches = bool(matched_values)
    denied = matches if rule.effect == "deny" else not matches
    return {"denied": denied, "matched_values": matched_values}


async def _matched_rule_values(*, rule, context: GuardrailEvaluationContext) -> list[str]:
    values = [value.strip() for value in rule.values if value.strip()]
    if rule.rule_type == "prompt_contains":
        target_text = _guardrail_target_text(context).lower()
        return [value for value in values if value.lower() in target_text]
    elif rule.rule_type == "prompt_regex":
        return await _matched_regex_values(
            values=values, prompt_text=_guardrail_target_text(context)
        )
    elif rule.rule_type == "pii":
        return await _matched_detector_values(
            rule=rule,
            values=values,
            prompt_text=_guardrail_target_text(context),
        )
    return []


def _rule_applies_to_phase(*, rule, phase: str) -> bool:
    rule_phase = getattr(rule, "phase", "both")
    return rule_phase in {"both", phase}


async def _rule_matchers_apply(
    *,
    rule,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> bool:
    matchers = getattr(rule, "matchers", None)
    if matchers is None:
        matchers = await repository.list_rule_matchers(
            org_id=context.org_id,
            rule_id=rule.id,
            db=db,
        )
    if not matchers:
        return True
    subject = _guardrail_dimension_subject(context)
    stage = (
        PolicyDimensionStage.RESPONSE_GUARDRAIL
        if context.phase == "response"
        else PolicyDimensionStage.REQUEST_GUARDRAIL
    )
    for matcher in matchers:
        if not evaluate_matcher(
            subject=subject,
            dimension=matcher.dimension,
            operator=matcher.operator,
            value=matcher.value_json,
            stage=stage,
        ):
            return False
    return True


def _guardrail_dimension_subject(context: GuardrailEvaluationContext) -> dict:
    return {
        "org_id": context.org_id,
        "team_id": context.team_id,
        "project_id": context.project_id,
        "virtual_key_id": context.virtual_key_id,
        "provider_id": context.provider_id,
        "credential_pool_id": context.pool_id,
        "provider_model_offering_id": context.provider_model_offering_id,
        "public_model_id": context.public_model_id,
        "public_model_name": context.public_model_name,
        "route_candidate_id": context.route_candidate_id,
        "gateway_endpoint": context.gateway_endpoint,
        "requested_model": context.requested_model,
        "provider_model": context.provider_model,
    }


def _rule_denial_reason(rule) -> str:
    if rule.effect == "allow":
        return f"{rule.rule_type}_allowlist_miss"
    return f"{rule.rule_type}_{rule.effect}"


def _guardrail_event_metadata(*, rule, evaluation: dict, mode: str, phase: str) -> dict:
    metadata = {
        "enforcement_mode": mode,
        "phase": phase,
    }
    if rule.effect == "allow":
        metadata["allowed_values"] = rule.values
    else:
        metadata["allowed_values"] = []
    if rule.rule_type == "pii":
        metadata["pii_types"] = evaluation["matched_values"]
        metadata["matched_values_redacted"] = True
    else:
        metadata["matched_values"] = evaluation["matched_values"]
    return metadata


def _guardrail_target_text(context: GuardrailEvaluationContext) -> str:
    if context.phase == "response":
        return context.response_text
    return context.prompt_text


async def _matched_detector_values(*, rule, values: list[str], prompt_text: str) -> list[str]:
    config = getattr(rule, "config", None) or {}
    detector_name = config.get("detector")
    if not isinstance(detector_name, str):
        detector_name = DEFAULT_PII_DETECTOR
    detector = get_detector(detector_name)
    if detector is None:
        return []
    result = await detector.detect(
        text=prompt_text[:GUARDRAIL_SCAN_CHAR_LIMIT], values=values, config=config
    )
    return result.matched_values


_logger = structlog.get_logger(__name__)
# Text scanned by prompt_regex / PII detectors is capped, and each match runs off the
# event loop under a wall-clock budget, so a catastrophic-backtracking pattern (in a
# stored rule or a /simulate payload) cannot hang the worker and starve other requests.
GUARDRAIL_SCAN_CHAR_LIMIT = 65_536
GUARDRAIL_REGEX_TIMEOUT_SECONDS = 1.0


async def _matched_regex_values(*, values: list[str], prompt_text: str) -> list[str]:
    text = prompt_text[:GUARDRAIL_SCAN_CHAR_LIMIT]
    matched: list[str] = []
    for value in values:
        try:
            pattern = re.compile(value, re.IGNORECASE)
        except re.error:
            continue
        try:
            found = await asyncio.wait_for(
                asyncio.to_thread(lambda p=pattern, t=text: p.search(t) is not None),
                timeout=GUARDRAIL_REGEX_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            _logger.warning("guardrail_regex_timeout", pattern_prefix=value[:48])
            continue
        if found:
            matched.append(value)
    return matched


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
    fallback: GuardrailAssignment,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if scope_type == "team":
        return team_id or fallback.team_id, None, None
    if scope_type == "project":
        return None, project_id or fallback.project_id, None
    if scope_type == "virtual_key":
        return None, None, virtual_key_id or fallback.virtual_key_id
    return None, None, None


def _effective_rule_mode(*, policy_mode: str, assignments: list[GuardrailAssignment]) -> str:
    if policy_mode == "monitor":
        return "dry_run"
    if any(assignment.enforcement_mode == "enforce" for assignment in assignments):
        return "enforce"
    return "dry_run"


def _effective_rule_assignment(
    *,
    mode: str,
    assignments: list[GuardrailAssignment],
) -> GuardrailAssignment | None:
    if not assignments:
        return None
    candidates = (
        [assignment for assignment in assignments if assignment.enforcement_mode == "enforce"]
        if mode == "enforce"
        else assignments
    )
    return max(candidates, key=lambda assignment: _assignment_specificity(assignment.scope_type))


def _assignment_specificity(scope_type: str) -> int:
    return {
        "org": 0,
        "team": 1,
        "project": 2,
        "virtual_key": 3,
    }.get(scope_type, -1)


def _assignment_scope_ids_from_payload(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if scope_type == "team":
        return team_id, None, None
    if scope_type == "project":
        return None, project_id, None
    if scope_type == "virtual_key":
        return None, None, virtual_key_id
    return None, None, None


async def _validate_assignment_target(
    *,
    org_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> None:
    if scope_type == "org":
        if team_id is not None or project_id is not None or virtual_key_id is not None:
            raise GuardrailAssignmentTargetNotFoundError
        return
    if scope_type == "team":
        if team_id is None or project_id is not None or virtual_key_id is not None:
            raise GuardrailAssignmentTargetNotFoundError
        if await repository.get_team(org_id=org_id, team_id=team_id, db=db) is None:
            raise GuardrailAssignmentTargetNotFoundError
        return
    if scope_type == "project":
        if project_id is None or virtual_key_id is not None:
            raise GuardrailAssignmentTargetNotFoundError
        project = await repository.get_project(org_id=org_id, project_id=project_id, db=db)
        if project is None:
            raise GuardrailAssignmentTargetNotFoundError
        if team_id is not None and team_id != project.team_id:
            raise GuardrailAssignmentTargetNotFoundError
        return
    if scope_type == "virtual_key":
        if virtual_key_id is None:
            raise GuardrailAssignmentTargetNotFoundError
        virtual_key = await repository.get_virtual_key(
            org_id=org_id, virtual_key_id=virtual_key_id, db=db
        )
        if virtual_key is None:
            raise GuardrailAssignmentTargetNotFoundError
        project = await repository.get_project(
            org_id=org_id, project_id=virtual_key.project_id, db=db
        )
        if project is None:
            raise GuardrailAssignmentTargetNotFoundError
        if project_id is not None and project_id != virtual_key.project_id:
            raise GuardrailAssignmentTargetNotFoundError
        if team_id is not None and team_id != project.team_id:
            raise GuardrailAssignmentTargetNotFoundError
        return
    else:
        raise GuardrailAssignmentTargetNotFoundError


def _is_org_guardrail_viewer(actor: AuthenticatedUser) -> bool:
    return (
        "*" in actor.permissions
        or "guardrails.view" in actor.permissions
        or "guardrails.manage" in actor.permissions
        or actor.role in {"org_owner", "org_admin", "org_viewer"}
    )


def _managed_scope_ids(actor: AuthenticatedUser) -> tuple[set[UUID], set[UUID]]:
    team_ids = {
        membership.team_id
        for membership in actor.team_memberships
        if membership.role == "team_admin"
    }
    project_ids = {
        membership.project_id
        for membership in actor.project_memberships
        if membership.role == "project_admin"
    }
    return team_ids, project_ids


async def _visible_assignments(
    *,
    actor: AuthenticatedUser | None,
    scope: Scope,
    db: AsyncSession,
) -> list[GuardrailAssignment]:
    assignments = await repository.list_assignments(org_id=scope.org_id, db=db)
    if actor is None or _is_org_guardrail_viewer(actor):
        return assignments

    team_ids, project_ids = _managed_scope_ids(actor)
    visible: list[GuardrailAssignment] = []
    for assignment in assignments:
        if assignment.scope_type == "org":
            continue
        if assignment.team_id in team_ids:
            visible.append(assignment)
            continue
        if assignment.project_id is not None:
            project = await repository.get_project(
                org_id=scope.org_id,
                project_id=assignment.project_id,
                db=db,
            )
            if project is not None and (project.id in project_ids or project.team_id in team_ids):
                visible.append(assignment)
            continue
        if assignment.virtual_key_id is not None:
            virtual_key = await repository.get_virtual_key(
                org_id=scope.org_id,
                virtual_key_id=assignment.virtual_key_id,
                db=db,
            )
            if virtual_key is None:
                continue
            project = await repository.get_project(
                org_id=scope.org_id,
                project_id=virtual_key.project_id,
                db=db,
            )
            if project is not None and (project.id in project_ids or project.team_id in team_ids):
                visible.append(assignment)
    return visible


async def _impact_from_assignments(
    *, org_id: UUID, assignments: list[GuardrailAssignment], db: AsyncSession
) -> GuardrailImpactResponse:
    teams: dict[UUID, GuardrailImpactTarget] = {}
    projects: dict[UUID, GuardrailImpactTarget] = {}
    project_models = await _affected_projects(org_id=org_id, assignments=assignments, db=db)
    for project in project_models:
        projects[project.id] = GuardrailImpactTarget(id=project.id, name=project.name)
    project_names = {project.id: project.name for project in project_models}
    keys = await repository.list_virtual_keys_for_project_ids(
        org_id=org_id,
        project_ids=[project.id for project in project_models],
        db=db,
    )
    virtual_keys = {
        key.id: GuardrailImpactVirtualKey(
            id=key.id,
            name=key.name,
            project_id=key.project_id,
            project_name=project_names.get(key.project_id, "Unknown project"),
        )
        for key in keys
    }
    for assignment in assignments:
        if assignment.scope_type == "team" and assignment.team_id is not None:
            team = await repository.get_team(org_id=org_id, team_id=assignment.team_id, db=db)
            if team is not None:
                teams[team.id] = GuardrailImpactTarget(id=team.id, name=team.name)
        elif assignment.scope_type == "virtual_key" and assignment.virtual_key_id is not None:
            key = await repository.get_virtual_key(
                org_id=org_id,
                virtual_key_id=assignment.virtual_key_id,
                db=db,
            )
            if key is None:
                continue
            project = await repository.get_project(org_id=org_id, project_id=key.project_id, db=db)
            if project is None:
                continue
            virtual_keys[key.id] = GuardrailImpactVirtualKey(
                id=key.id,
                name=key.name,
                project_id=project.id,
                project_name=project.name,
            )
            projects[project.id] = GuardrailImpactTarget(id=project.id, name=project.name)
    return GuardrailImpactResponse(
        affected_teams=list(teams.values()),
        affected_projects=list(projects.values()),
        affected_virtual_keys=list(virtual_keys.values()),
        affected_team_count=len(teams),
        affected_project_count=len(projects),
        affected_virtual_key_count=len(virtual_keys),
    )


async def _affected_projects(
    *, org_id: UUID, assignments: list[GuardrailAssignment], db: AsyncSession
) -> list:
    project_ids = [item.project_id for item in assignments if item.project_id is not None]
    team_ids = [item.team_id for item in assignments if item.team_id is not None]
    projects = []
    if any(item.scope_type == "org" for item in assignments):
        projects.extend(await repository.list_all_projects(org_id=org_id, db=db))
    if team_ids:
        projects.extend(
            await repository.list_projects_for_team_ids(org_id=org_id, team_ids=team_ids, db=db)
        )
    for project_id in project_ids:
        project = await repository.get_project(org_id=org_id, project_id=project_id, db=db)
        if project is not None:
            projects.append(project)
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
        name=policy.name,
        description=policy.description,
        enforcement_mode=policy.enforcement_mode,
        is_active=policy.is_active,
        rules=rule_responses,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _validate_rule_matchers(rules) -> None:
    for rule in rules:
        stage = (
            PolicyDimensionStage.RESPONSE_GUARDRAIL
            if rule.phase == "response"
            else PolicyDimensionStage.REQUEST_GUARDRAIL
        )
        for matcher in rule.matchers:
            try:
                validate_matcher(
                    dimension=matcher.dimension,
                    operator=matcher.operator,
                    value=matcher.value_json,
                    stage=stage,
                )
            except (PolicyValidationError, ValueError) as exc:
                raise ValueError("invalid guardrail matcher") from exc


def _to_assignment_response(
    assignment: GuardrailAssignment,
    policy_name: str,
) -> GuardrailAssignmentResponse:
    return GuardrailAssignmentResponse(
        id=assignment.id,
        org_id=assignment.org_id,
        policy_id=assignment.policy_id,
        policy_name=policy_name,
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
