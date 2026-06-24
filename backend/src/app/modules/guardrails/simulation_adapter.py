from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails import facade
from app.modules.guardrails.evaluation import (
    RuntimeGuardrailAssignmentRef,
    RuntimeGuardrailPolicyRef,
    RuntimeGuardrailRuleInput,
    RuntimeGuardrailRuleRef,
    RuntimeMatcherInput,
    evaluate_guardrail_rules_readonly,
)
from app.modules.guardrails.internal import repository
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.guardrails.validation import validate_guardrail_rule_payload
from app.modules.policy_simulation.errors import (
    PolicySimulationPermissionError,
    PolicySimulationValidationError,
)
from app.modules.policy_simulation.schemas import (
    PolicySimulationDecision,
    PolicySimulationDraft,
    PolicySimulationGuardrailResult,
    PolicySimulationRequest,
    PolicySimulationWarning,
)
from app.modules.policy_simulation.types import (
    SimulationAssignmentContext,
    SimulationReplacementPolicy,
    SimulationRouteContext,
    SimulationTargetContext,
)


@dataclass(frozen=True)
class GuardrailSimulationOutcome:
    results: list[PolicySimulationGuardrailResult]
    decisions: list[PolicySimulationDecision]
    warnings: list[PolicySimulationWarning]
    final_decision: str
    denied_stage: str | None
    denied_reason: str | None


def validate_guardrail_draft_policy(draft: PolicySimulationDraft) -> None:
    if draft.guardrail_policy is None:
        raise PolicySimulationValidationError
    try:
        validate_guardrail_rule_payload(draft.guardrail_policy.rules)
    except ValueError as exc:
        raise PolicySimulationValidationError from exc


async def validate_guardrail_replacement_policy(
    *,
    org_id: UUID,
    policy_id: UUID,
    actor_is_scoped: bool,
    actor_can_manage_all: bool,
    assignment_visible: Callable[[SimulationAssignmentContext], Awaitable[bool]],
    db: AsyncSession,
) -> SimulationReplacementPolicy:
    policy = await repository.get_policy(policy_id=policy_id, org_id=org_id, db=db)
    if policy is None or not policy.is_active:
        if actor_is_scoped:
            raise PolicySimulationPermissionError
        raise PolicySimulationValidationError
    if not actor_can_manage_all:
        assignments = await repository.list_policy_assignments(
            org_id=org_id,
            policy_id=policy.id,
            active_only=True,
            db=db,
        )
        for assignment in assignments:
            if await assignment_visible(assignment):
                break
        else:
            raise PolicySimulationPermissionError
    return SimulationReplacementPolicy(
        concrete_id=policy.id,
        shared_policy_id=policy.policy_id,
    )


async def simulate_guardrails_for_attempts(
    *,
    payload: PolicySimulationRequest,
    attempts: list[tuple[UUID | None, SimulationRouteContext, bool]],
    target: SimulationTargetContext,
    replacement_index: dict[UUID, SimulationReplacementPolicy],
    initial_final_decision: str,
    initial_denied_stage: str | None,
    initial_denied_reason: str | None,
    db: AsyncSession,
) -> GuardrailSimulationOutcome:
    warnings: list[PolicySimulationWarning] = []
    results: list[PolicySimulationGuardrailResult] = []
    decisions: list[PolicySimulationDecision] = []
    final_decision = initial_final_decision
    denied_stage = initial_denied_stage
    denied_reason = initial_denied_reason

    if payload.guardrail_input is None:
        warnings.append(
            PolicySimulationWarning(
                code="guardrail_content_not_provided",
                message=(
                    "Guardrail detectors were not executed because no sample content "
                    "was provided."
                ),
            )
        )
    for route_candidate_id, resolved, is_primary_attempt in attempts:
        for phase in ("request", "response"):
            context = _guardrail_context(payload=payload, attempt=resolved, phase=phase)
            detector_mode = _guardrail_detector_mode(payload=payload, phase=phase)
            rules = await _effective_guardrail_rules(
                context=context,
                payload=payload,
                target=target,
                replacement_index=replacement_index,
                db=db,
            )
            evaluations = await evaluate_guardrail_rules_readonly(
                context=context,
                rules=rules,
                detector_mode=detector_mode,
                db=db,
            )
            for evaluation in evaluations:
                results.append(
                    PolicySimulationGuardrailResult(
                        route_candidate_id=route_candidate_id,
                        policy_id=evaluation.policy_id,
                        policy_name=evaluation.policy_name,
                        policy_revision_id=evaluation.policy_revision_id,
                        policy_revision_number=evaluation.policy_revision_number,
                        rule_id=evaluation.rule_id,
                        rule_name=evaluation.rule_name,
                        assignment_id=evaluation.assignment_id,
                        assignment_mode=evaluation.assignment_mode,
                        assignment_scope_label=evaluation.assignment_scope_label,
                        phase=evaluation.phase,
                        rule_type=evaluation.rule_type,
                        effect=evaluation.effect,
                        applicability_matched=evaluation.applicability_matched,
                        detector_evaluated=evaluation.detector_evaluated,
                        matched_values=evaluation.matched_values,
                        decision=evaluation.decision,
                        reason_code=evaluation.reason_code,
                        message=evaluation.message,
                        draft_ref=evaluation.draft_ref,
                    )
                )
                if is_primary_attempt and evaluation.denied:
                    enforced = evaluation.decision == "blocked"
                    if final_decision != "deny":
                        final_decision = "deny" if enforced else "would_deny"
                        denied_stage = f"{phase}_guardrail"
                        denied_reason = evaluation.reason_code
                    decisions.append(
                        PolicySimulationDecision(
                            decision_type="guardrail",
                            stage=f"{phase}_guardrail",
                            outcome="denied" if enforced else "would_deny",
                            effective_action="deny" if enforced else "would_deny",
                            enforced=enforced,
                            policy_id=evaluation.policy_id,
                            policy_name=evaluation.policy_name,
                            policy_kind="guardrail",
                            policy_revision_id=evaluation.policy_revision_id,
                            policy_revision_number=evaluation.policy_revision_number,
                            assignment_id=evaluation.assignment_id,
                            assignment_mode=evaluation.assignment_mode,
                            assignment_scope_label=evaluation.assignment_scope_label,
                            rule_id=evaluation.rule_id,
                            rule_name=evaluation.rule_name,
                            route_candidate_id=route_candidate_id,
                            reason_code=evaluation.reason_code,
                            message=evaluation.message,
                            draft_ref=evaluation.draft_ref,
                        )
                    )
    if payload.guardrail_input is None or payload.guardrail_input.response_text is None:
        warnings.append(
            PolicySimulationWarning(
                code="response_guardrail_content_not_provided",
                message=(
                    "Response guardrail detectors were not executed because no response "
                    "text was provided."
                ),
            )
        )
    return GuardrailSimulationOutcome(
        results=results,
        decisions=decisions,
        warnings=warnings,
        final_decision=final_decision,
        denied_stage=denied_stage,
        denied_reason=denied_reason,
    )


async def _effective_guardrail_rules(
    *,
    context: GuardrailEvaluationContext,
    payload: PolicySimulationRequest,
    target: SimulationTargetContext,
    replacement_index: dict[UUID, SimulationReplacementPolicy],
    db: AsyncSession,
) -> list[RuntimeGuardrailRuleInput]:
    saved_rules = await facade.runtime_rules_for_context_readonly(context=context, db=db)
    replaced_policy_ids = {
        replacement_index[draft.existing_policy_id].concrete_id
        for draft in payload.drafts
        if draft.kind == "guardrail"
        and draft.operation == "replace_policy"
        and draft.existing_policy_id is not None
        and draft.existing_policy_id in replacement_index
    }
    active_replaced_policy_ids = {
        rule.policy_ref.policy_id
        for rule in saved_rules
        if rule.policy_ref.policy_id in replaced_policy_ids
    }
    effective_rules = [
        rule for rule in saved_rules if rule.policy_ref.policy_id not in replaced_policy_ids
    ]
    effective_rules.extend(
        _runtime_guardrail_draft_rules(
            payload.drafts,
            target=target,
            active_replaced_policy_ids=active_replaced_policy_ids,
            replacement_index=replacement_index,
        )
    )
    return _sort_runtime_guardrail_rules(effective_rules)


def _runtime_guardrail_draft_rules(
    drafts: list[PolicySimulationDraft],
    *,
    target: SimulationTargetContext,
    active_replaced_policy_ids: set[UUID | None],
    replacement_index: dict[UUID, SimulationReplacementPolicy],
) -> list[RuntimeGuardrailRuleInput]:
    runtime_rules: list[RuntimeGuardrailRuleInput] = []
    for draft_index, draft in enumerate(drafts):
        if draft.kind != "guardrail" or draft.guardrail_policy is None:
            continue
        if not draft.guardrail_policy.is_active:
            continue
        if not _guardrail_draft_applies(
            draft=draft,
            target=target,
            active_replaced_policy_ids=active_replaced_policy_ids,
            replacement_index=replacement_index,
        ):
            continue
        assignment_mode = (
            draft.assignment.guardrail_assignment_mode
            if draft.assignment and draft.assignment.guardrail_assignment_mode
            else "enforce"
        )
        policy_ref = RuntimeGuardrailPolicyRef(
            policy_key=f"draft[{draft_index}]:guardrail_policy",
            policy_id=None,
            policy_revision_id=None,
            policy_name=draft.guardrail_policy.name,
            policy_revision_number=None,
            enforcement_mode=draft.guardrail_policy.enforcement_mode,
            draft_ref=f"draft[{draft_index}]:guardrail_policy",
        )
        assignment_ref = RuntimeGuardrailAssignmentRef(
            assignment_id=None,
            assignment_mode=assignment_mode,
            assignment_scope_type=draft.assignment.scope_type if draft.assignment else None,
            assignment_scope_label=draft.assignment.scope_type if draft.assignment else None,
            draft_ref=f"draft[{draft_index}]:guardrail_policy.assignment",
        )
        for rule_index, rule in enumerate(draft.guardrail_policy.rules):
            if not rule.is_active:
                continue
            draft_ref = f"draft[{draft_index}]:guardrail_policy.rules[{rule_index}]"
            for phase in _guardrail_rule_phases(rule.phase):
                runtime_rules.append(
                    RuntimeGuardrailRuleInput(
                        policy_ref=policy_ref,
                        assignment_refs=[assignment_ref],
                        rule_ref=RuntimeGuardrailRuleRef(
                            rule_id=None,
                            rule_name=None,
                            rule_index=rule_index,
                            draft_ref=draft_ref,
                        ),
                        phase=phase,
                        source_phase=rule.phase,
                        rule_type=rule.rule_type,
                        effect=rule.effect,
                        values=rule.values,
                        config=rule.config,
                        matchers=[
                            RuntimeMatcherInput(
                                dimension=matcher.dimension,
                                operator=matcher.operator,
                                value_json=matcher.value_json,
                            )
                            for matcher in rule.matchers
                        ],
                        priority=rule.priority,
                        is_active=rule.is_active,
                    )
                )
    return runtime_rules


def _guardrail_draft_applies(
    *,
    draft: PolicySimulationDraft,
    target: SimulationTargetContext,
    active_replaced_policy_ids: set[UUID | None],
    replacement_index: dict[UUID, SimulationReplacementPolicy],
) -> bool:
    if draft.operation == "replace_policy":
        replacement = (
            replacement_index.get(draft.existing_policy_id)
            if draft.existing_policy_id is not None
            else None
        )
        if replacement is None:
            return False
        if draft.assignment is None:
            return replacement.concrete_id in active_replaced_policy_ids
    return _draft_assignment_matches_target(draft=draft, target=target)


def _draft_assignment_matches_target(
    *, draft: PolicySimulationDraft, target: SimulationTargetContext
) -> bool:
    assignment = draft.assignment
    if assignment is None:
        return True
    if assignment.scope_type == "org":
        return True
    if assignment.scope_type == "team":
        return assignment.team_id == target.team_id
    if assignment.scope_type == "project":
        return assignment.project_id == target.project_id
    if assignment.scope_type == "virtual_key":
        return assignment.virtual_key_id == target.virtual_key_id
    return False


def _sort_runtime_guardrail_rules(
    rules: list[RuntimeGuardrailRuleInput],
) -> list[RuntimeGuardrailRuleInput]:
    return sorted(
        rules,
        key=lambda item: (
            item.priority,
            item.source_created_at is None,
            item.source_created_at.isoformat() if item.source_created_at else "",
            item.rule_ref.rule_index,
        ),
    )


def _guardrail_rule_phases(source_phase: str) -> list[str]:
    if source_phase == "both":
        return ["request", "response"]
    return [source_phase]


def _guardrail_context(
    *,
    payload: PolicySimulationRequest,
    attempt: SimulationRouteContext,
    phase: str,
) -> GuardrailEvaluationContext:
    guardrail_input = payload.guardrail_input
    prompt_text = ""
    response_text = ""
    if guardrail_input is not None:
        prompt_text = (
            guardrail_input.prompt_text
            if guardrail_input.prompt_text is not None
            else _messages_text(guardrail_input.messages)
        )
        response_text = guardrail_input.response_text or ""
    return GuardrailEvaluationContext(
        org_id=attempt.org_id,
        team_id=attempt.team_id,
        project_id=attempt.project_id,
        virtual_key_id=attempt.virtual_key_id,
        provider_id=attempt.provider_id,
        pool_id=attempt.pool_id,
        provider_model_offering_id=attempt.model_offering_id,
        public_model_id=attempt.public_model_id,
        public_model_name=attempt.public_model_name,
        route_candidate_id=attempt.route_candidate_id,
        gateway_endpoint=payload.gateway_endpoint,
        requested_model=payload.requested_model,
        provider_model=attempt.provider_model,
        prompt_text=prompt_text,
        response_text=response_text,
        phase=phase,
    )


def _guardrail_detector_mode(*, payload: PolicySimulationRequest, phase: str) -> str:
    if payload.guardrail_input is None:
        return "applicability_only"
    if phase == "response" and payload.guardrail_input.response_text is None:
        return "applicability_only"
    if phase == "request" and not (
        payload.guardrail_input.prompt_text or payload.guardrail_input.messages
    ):
        return "applicability_only"
    return "execute_detectors"


def _messages_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(_content_to_text(message.get("content")) for message in messages)


def _content_to_text(content: Any) -> str:
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
