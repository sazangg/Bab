import re
from uuid import UUID

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
    GuardrailPolicyResponse,
    GuardrailRuleResponse,
    GuardrailSimulationMatch,
    GuardrailSimulationRequest,
    GuardrailSimulationResponse,
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
    *, policy_id: UUID, scope: Scope, db: AsyncSession
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
    return await _impact_from_assignments(org_id=scope.org_id, assignments=assignments, db=db)


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
        assignment = await repository.create_assignment(
            org_id=scope.org_id,
            policy_id=payload.policy_id,
            scope_type=payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            enforcement_mode=payload.enforcement_mode,
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
        assignment.policy_id = policy_id
        assignment.scope_type = scope_type
        assignment.team_id = team_id
        assignment.project_id = project_id
        assignment.virtual_key_id = virtual_key_id
        if payload.enforcement_mode is not None:
            assignment.enforcement_mode = payload.enforcement_mode
        if payload.is_active is not None:
            assignment.is_active = payload.is_active
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
    *, assignment_id: UUID, scope: Scope, db: AsyncSession
) -> GuardrailImpactResponse:
    assignment = await repository.get_assignment(
        assignment_id=assignment_id,
        org_id=scope.org_id,
        db=db,
    )
    if assignment is None:
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
) -> None:
    await _evaluate_context(context=context, db=db)


async def evaluate_response(
    *,
    context: GuardrailEvaluationContext,
    response_text: str,
    db: AsyncSession,
) -> None:
    await _evaluate_context(
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
        and _rule_supports_phase(rule=rule, phase="response")
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
) -> None:
    assignments = await repository.list_effective_assignments(
        org_id=context.org_id,
        team_id=context.team_id,
        project_id=context.project_id,
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
    assignments_by_policy: dict[UUID, list[GuardrailAssignment]] = {}
    for assignment in assignments:
        assignments_by_policy.setdefault(assignment.policy_id, []).append(assignment)
    policy_mode = {policy.id: policy.enforcement_mode for policy in policies.values()}
    for rule in rules:
        if (
            not rule.is_active
            or not _rule_applies_to_phase(rule=rule, phase=context.phase)
            or not _rule_supports_phase(rule=rule, phase=context.phase)
        ):
            continue
        evaluation = await _evaluate_rule(rule=rule, context=context)
        if not evaluation["denied"]:
            continue
        mode = _effective_rule_mode(
            policy_mode=policy_mode.get(rule.policy_id, "enforce"),
            assignments=assignments_by_policy.get(rule.policy_id, []),
        )
        await _record_event(
            context=context,
            policy_id=rule.policy_id,
            rule_id=rule.id,
            decision="blocked" if mode == "enforce" else "dry_run",
            reason=_rule_denial_reason(rule),
            metadata={
                "matched_values": evaluation["matched_values"],
                "allowed_values": rule.values if rule.effect == "allow" else [],
                "enforcement_mode": mode,
                "phase": context.phase,
            },
            db=db,
        )
        if mode == "enforce":
            rule_label = "allowlist" if rule.effect == "allow" else rule.rule_type
            raise GuardrailDeniedError(
                detail=f"{context.phase} blocked by guardrail {rule_label} rule",
                policy_id=rule.policy_id,
                rule_id=rule.id,
            )
    await _record_event(
        context=context,
        policy_id=None,
        rule_id=None,
        decision="allowed",
        reason=f"{context.phase}_guardrails_passed",
        metadata={"phase": context.phase},
        db=db,
    )


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
    db: AsyncSession,
) -> list[GuardrailEventResponse]:
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
        db=db,
    )
    return [_to_event_response(event) for event in events]


async def simulate(
    *,
    payload: GuardrailSimulationRequest,
    scope: Scope,
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
    if rule.rule_type == "model":
        current = {context.requested_model.lower(), context.provider_model.lower()}
        return [value for value in values if value.lower() in current]
    elif rule.rule_type == "provider":
        current = {str(context.provider_id).lower()}
        return [value for value in values if value.lower() in current]
    elif rule.rule_type == "pool":
        current = {str(context.pool_id).lower()}
        return [value for value in values if value.lower() in current]
    elif rule.rule_type == "prompt_contains":
        target_text = _guardrail_target_text(context).lower()
        return [value for value in values if value.lower() in target_text]
    elif rule.rule_type == "prompt_regex":
        return _matched_regex_values(values=values, prompt_text=_guardrail_target_text(context))
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


def _rule_supports_phase(*, rule, phase: str) -> bool:
    if phase == "request":
        return True
    return rule.rule_type in {"prompt_contains", "prompt_regex", "pii"}


def _rule_denial_reason(rule) -> str:
    if rule.effect == "allow":
        return f"{rule.rule_type}_allowlist_miss"
    return f"{rule.rule_type}_{rule.effect}"


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
    result = await detector.detect(text=prompt_text, values=values, config=config)
    return result.matched_values


def _matched_regex_values(*, values: list[str], prompt_text: str) -> list[str]:
    matched: list[str] = []
    for value in values:
        try:
            if re.search(value, prompt_text, re.IGNORECASE):
                matched.append(value)
        except re.error:
            continue
    return matched


async def _record_event(
    *,
    context: GuardrailEvaluationContext,
    policy_id: UUID | None,
    rule_id: UUID | None,
    decision: str,
    reason: str,
    metadata: dict,
    db: AsyncSession,
) -> None:
    await repository.create_event(
        org_id=context.org_id,
        policy_id=policy_id,
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
    if any(assignment.enforcement_mode == "dry_run" for assignment in assignments):
        return "dry_run"
    if policy_mode == "monitor":
        return "dry_run"
    return "enforce"


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
        requested_model=event.requested_model,
        provider_model=event.provider_model,
        metadata=event.metadata_,
        created_at=event.created_at,
    )
