from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import RecordActivityEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails.errors import (
    GuardrailAssignmentConflictError,
    GuardrailAssignmentNotFoundError,
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
    GuardrailPolicyResponse,
    GuardrailRuleResponse,
    UpdateGuardrailAssignmentRequest,
    UpdateGuardrailPolicyRequest,
)


async def list_policies(*, scope: Scope, db: AsyncSession) -> list[GuardrailPolicyResponse]:
    policies = await repository.list_policies(org_id=scope.org_id, db=db)
    rules = await repository.list_policy_rules(
        org_id=scope.org_id,
        policy_ids=[policy.id for policy in policies],
        db=db,
    )
    rules_by_policy = _rules_by_policy(rules)
    return [_to_policy_response(policy, rules_by_policy.get(policy.id, [])) for policy in policies]


async def create_policy(
    *,
    payload: CreateGuardrailPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailPolicyResponse:
    async with transaction(db):
        policy = await repository.create_policy(
            org_id=scope.org_id,
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
            db=db,
        )
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.policy_created",
                message=f"Created guardrail policy {policy.name}.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"policy_id": str(policy.id)},
            ),
            db=db,
        )
    rules = await repository.list_policy_rules(org_id=scope.org_id, policy_ids=[policy.id], db=db)
    return _to_policy_response(policy, rules)


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
        for field in ("name", "description", "enforcement_mode", "is_active"):
            if field in payload.model_fields_set:
                setattr(policy, field, getattr(payload, field))
        if payload.rules is not None:
            await repository.replace_rules(
                org_id=scope.org_id,
                policy_id=policy.id,
                rules=[rule.model_dump() for rule in payload.rules],
                db=db,
            )
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.policy_updated",
                message=f"Updated guardrail policy {policy.name}.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"policy_id": str(policy.id)},
            ),
            db=db,
        )
    rules = await repository.list_policy_rules(org_id=scope.org_id, policy_ids=[policy.id], db=db)
    return _to_policy_response(policy, rules)


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
        await repository.delete_policy(policy=policy, db=db)
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.policy_deleted",
                message=f"Deleted guardrail policy {policy.name}.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"policy_id": str(policy_id)},
            ),
            db=db,
        )


async def list_assignments(*, scope: Scope, db: AsyncSession) -> list[GuardrailAssignmentResponse]:
    assignments = await repository.list_assignments(org_id=scope.org_id, db=db)
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
        existing = await repository.find_assignment_for_scope(
            org_id=scope.org_id,
            policy_id=payload.policy_id,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            allocation_id=payload.allocation_id,
            virtual_key_id=payload.virtual_key_id,
            db=db,
        )
        if existing is not None:
            raise GuardrailAssignmentConflictError
        assignment = await repository.create_assignment(
            org_id=scope.org_id,
            policy_id=payload.policy_id,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            allocation_id=payload.allocation_id,
            virtual_key_id=payload.virtual_key_id,
            is_active=payload.is_active,
            db=db,
        )
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.assignment_created",
                message=f"Assigned guardrail policy {policy.name}.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"policy_id": str(policy.id), "scope_type": payload.scope_type},
            ),
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
        team_id, project_id, allocation_id, virtual_key_id = _assignment_scope_ids(
            scope_type=scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            allocation_id=payload.allocation_id,
            virtual_key_id=payload.virtual_key_id,
            fallback=assignment,
        )
        existing = await repository.find_assignment_for_scope(
            org_id=scope.org_id,
            policy_id=policy_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            allocation_id=allocation_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
        if existing is not None and existing.id != assignment.id:
            raise GuardrailAssignmentConflictError
        assignment.policy_id = policy_id
        assignment.scope_type = scope_type
        assignment.team_id = team_id
        assignment.project_id = project_id
        assignment.allocation_id = allocation_id
        assignment.virtual_key_id = virtual_key_id
        if payload.is_active is not None:
            assignment.is_active = payload.is_active
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.assignment_updated",
                message="Updated guardrail assignment.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"assignment_id": str(assignment.id)},
            ),
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
        await repository.delete_assignment(assignment=assignment, db=db)
        await activity_facade.record_event(
            payload=RecordActivityEvent(
                org_id=scope.org_id,
                category="guardrail",
                severity="info",
                action="guardrail.assignment_deleted",
                message="Deleted guardrail assignment.",
                actor_user_id=actor.id,
                actor_email=actor.email,
                metadata={"assignment_id": str(assignment_id)},
            ),
            db=db,
        )


async def evaluate_request(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> None:
    assignments = await repository.list_effective_assignments(
        org_id=context.org_id,
        team_id=context.team_id,
        project_id=context.project_id,
        allocation_ids=context.allocation_chain_ids,
        virtual_key_id=context.virtual_key_id,
        db=db,
    )
    if not assignments:
        return
    policies = {
        policy.id: policy
        for policy in await repository.list_policies(org_id=context.org_id, db=db)
        if policy.is_active
    }
    policy_ids = [
        assignment.policy_id for assignment in assignments if assignment.policy_id in policies
    ]
    rules = await repository.list_policy_rules(org_id=context.org_id, policy_ids=policy_ids, db=db)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    for rule in rules:
        if not rule.is_active:
            continue
        denied = _rule_denies(rule=rule, context=context)
        if not denied:
            continue
        mode = policy_mode.get(rule.policy_id, "enforce")
        await _record_event(
            context=context,
            policy_id=rule.policy_id,
            rule_id=rule.id,
            decision="blocked" if mode == "enforce" else "warned",
            reason=f"{rule.rule_type}_{rule.effect}",
            db=db,
        )
        if mode == "enforce":
            raise GuardrailDeniedError(
                detail=f"request blocked by guardrail {rule.rule_type} rule",
                policy_id=rule.policy_id,
                rule_id=rule.id,
            )
    await _record_event(
        context=context,
        policy_id=None,
        rule_id=None,
        decision="allowed",
        reason="guardrails_passed",
        db=db,
    )


async def list_events(
    *,
    scope: Scope,
    decision: str | None = None,
    limit: int = 50,
    db: AsyncSession,
) -> list[GuardrailEventResponse]:
    events = await repository.list_events(
        org_id=scope.org_id,
        decision=decision,
        limit=limit,
        db=db,
    )
    return [_to_event_response(event) for event in events]


def _rule_denies(*, rule, context: GuardrailEvaluationContext) -> bool:
    values = {value.lower() for value in rule.values}
    if rule.rule_type == "model":
        current = {context.requested_model.lower(), context.provider_model.lower()}
    elif rule.rule_type == "provider":
        current = {str(context.provider_id).lower()}
    elif rule.rule_type == "pool":
        current = {str(context.pool_id).lower()}
    else:
        return False
    matches = bool(values.intersection(current))
    if rule.effect == "deny":
        return matches
    return not matches


async def _record_event(
    *,
    context: GuardrailEvaluationContext,
    policy_id: UUID | None,
    rule_id: UUID | None,
    decision: str,
    reason: str,
    db: AsyncSession,
) -> None:
    await repository.create_event(
        org_id=context.org_id,
        policy_id=policy_id,
        rule_id=rule_id,
        decision=decision,
        reason=reason,
        team_id=context.team_id,
        project_id=context.project_id,
        allocation_id=context.allocation_id,
        virtual_key_id=context.virtual_key_id,
        provider_id=context.provider_id,
        pool_id=context.pool_id,
        requested_model=context.requested_model,
        provider_model=context.provider_model,
        metadata={},
        db=db,
    )
    await db.commit()


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
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    fallback: GuardrailAssignment,
) -> tuple[UUID | None, UUID | None, UUID | None, UUID | None]:
    if scope_type == "team":
        return team_id or fallback.team_id, None, None, None
    if scope_type == "project":
        return None, project_id or fallback.project_id, None, None
    if scope_type == "allocation":
        return None, None, allocation_id or fallback.allocation_id, None
    if scope_type == "virtual_key":
        return None, None, None, virtual_key_id or fallback.virtual_key_id
    return None, None, None, None


def _to_policy_response(policy, rules) -> GuardrailPolicyResponse:
    return GuardrailPolicyResponse(
        id=policy.id,
        org_id=policy.org_id,
        name=policy.name,
        description=policy.description,
        enforcement_mode=policy.enforcement_mode,
        is_active=policy.is_active,
        rules=[GuardrailRuleResponse.model_validate(rule) for rule in rules],
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


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
        allocation_id=assignment.allocation_id,
        virtual_key_id=assignment.virtual_key_id,
        is_active=assignment.is_active,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _to_event_response(event: GuardrailEvent) -> GuardrailEventResponse:
    return GuardrailEventResponse(
        id=event.id,
        org_id=event.org_id,
        policy_id=event.policy_id,
        rule_id=event.rule_id,
        decision=event.decision,
        reason=event.reason,
        team_id=event.team_id,
        project_id=event.project_id,
        allocation_id=event.allocation_id,
        virtual_key_id=event.virtual_key_id,
        provider_id=event.provider_id,
        pool_id=event.pool_id,
        requested_model=event.requested_model,
        provider_model=event.provider_model,
        metadata=event.metadata_,
        created_at=event.created_at,
    )
