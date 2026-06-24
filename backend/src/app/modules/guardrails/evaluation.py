import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails.detectors.registry import DEFAULT_PII_DETECTOR, get_detector
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.policies.dimensions import PolicyDimensionStage, evaluate_matcher


@dataclass(frozen=True, slots=True)
class RuntimeMatcherInput:
    dimension: str
    operator: str
    value_json: Any = None


@dataclass(frozen=True, slots=True)
class RuntimeGuardrailPolicyRef:
    policy_key: str
    policy_id: UUID | None
    policy_revision_id: UUID | None
    policy_name: str | None
    policy_revision_number: int | None
    enforcement_mode: Literal["enforce", "monitor"]
    draft_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeGuardrailAssignmentRef:
    assignment_id: UUID | None
    assignment_mode: Literal["enforce", "dry_run"]
    assignment_scope_type: str | None
    assignment_scope_label: str | None
    draft_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeGuardrailRuleRef:
    rule_id: UUID | None
    rule_name: str | None
    rule_index: int
    draft_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeGuardrailRuleInput:
    policy_ref: RuntimeGuardrailPolicyRef
    assignment_refs: list[RuntimeGuardrailAssignmentRef]
    rule_ref: RuntimeGuardrailRuleRef
    phase: Literal["request", "response"]
    source_phase: Literal["request", "response", "both"]
    rule_type: str
    effect: Literal["allow", "deny"]
    values: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    matchers: list[RuntimeMatcherInput] = field(default_factory=list)
    priority: int = 100
    is_active: bool = True
    source_created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GuardrailReadonlyEvaluation:
    policy_id: UUID | None
    policy_revision_id: UUID | None
    rule_id: UUID | None
    assignment_id: UUID | None
    assignment_mode: str | None
    policy_name: str | None
    policy_revision_number: int | None
    rule_name: str | None
    assignment_scope_label: str | None
    phase: str
    rule_type: str
    effect: str
    applicability_matched: bool
    detector_evaluated: bool
    matched_values: list[str]
    denied: bool
    decision: str
    reason_code: str | None
    message: str | None
    draft_ref: str | None = None


async def evaluate_guardrail_rules_readonly(
    *,
    context: GuardrailEvaluationContext,
    rules: list[RuntimeGuardrailRuleInput],
    detector_mode: Literal["applicability_only", "execute_detectors"],
    db: AsyncSession,
) -> list[GuardrailReadonlyEvaluation]:
    del db
    results: list[GuardrailReadonlyEvaluation] = []
    for rule in rules:
        if not rule.is_active or rule.phase != context.phase:
            continue
        assignment_ref = _effective_assignment_ref(rule.assignment_refs)
        applicability_matched = guardrail_rule_matchers_apply(rule=rule, context=context)
        if not applicability_matched:
            results.append(
                _readonly_evaluation(
                    rule=rule,
                    assignment_ref=assignment_ref,
                    applicability_matched=False,
                    detector_evaluated=False,
                    matched_values=[],
                    denied=False,
                    decision="not_applicable",
                )
            )
            continue
        if detector_mode == "applicability_only" or not _has_detector_input(context):
            results.append(
                _readonly_evaluation(
                    rule=rule,
                    assignment_ref=assignment_ref,
                    applicability_matched=True,
                    detector_evaluated=False,
                    matched_values=[],
                    denied=False,
                    decision="not_evaluated",
                )
            )
            continue
        matched_values = await matched_guardrail_rule_values(rule=rule, context=context)
        matches = bool(matched_values)
        denied = matches if rule.effect == "deny" else not matches
        decision = _guardrail_decision(rule=rule, assignment_ref=assignment_ref, denied=denied)
        results.append(
            _readonly_evaluation(
                rule=rule,
                assignment_ref=assignment_ref,
                applicability_matched=True,
                detector_evaluated=True,
                matched_values=matched_values,
                denied=denied,
                decision=decision,
            )
        )
    return results


def guardrail_dimension_subject(context: GuardrailEvaluationContext) -> dict[str, Any]:
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


def guardrail_rule_matchers_apply(
    *,
    rule: RuntimeGuardrailRuleInput,
    context: GuardrailEvaluationContext,
) -> bool:
    if not rule.matchers:
        return True
    stage = (
        PolicyDimensionStage.RESPONSE_GUARDRAIL
        if context.phase == "response"
        else PolicyDimensionStage.REQUEST_GUARDRAIL
    )
    subject = guardrail_dimension_subject(context)
    return all(
        evaluate_matcher(
            subject=subject,
            dimension=matcher.dimension,
            operator=matcher.operator,
            value=matcher.value_json,
            stage=stage,
        )
        for matcher in rule.matchers
    )


async def matched_guardrail_rule_values(
    *,
    rule: RuntimeGuardrailRuleInput,
    context: GuardrailEvaluationContext,
) -> list[str]:
    values = [value.strip() for value in rule.values if value.strip()]
    target_text = guardrail_target_text(context)
    if rule.rule_type == "prompt_contains":
        lowered_text = target_text.lower()
        return [value for value in values if value.lower() in lowered_text]
    if rule.rule_type == "prompt_regex":
        return await matched_regex_values(values=values, prompt_text=target_text)
    if rule.rule_type == "pii":
        return await matched_detector_values(
            rule_type=rule.rule_type,
            values=values,
            config=rule.config,
            prompt_text=target_text,
        )
    return []


def guardrail_target_text(context: GuardrailEvaluationContext) -> str:
    if context.phase == "response":
        return context.response_text
    return context.prompt_text


async def matched_detector_values(
    *,
    rule_type: str,
    values: list[str],
    config: dict[str, Any],
    prompt_text: str,
) -> list[str]:
    if rule_type != "pii":
        return []
    detector_name = config.get("detector")
    if not isinstance(detector_name, str):
        detector_name = DEFAULT_PII_DETECTOR
    detector = get_detector(detector_name)
    if detector is None:
        return []
    result = await detector.detect(
        text=prompt_text[:GUARDRAIL_SCAN_CHAR_LIMIT],
        values=values,
        config=config,
    )
    return result.matched_values


async def matched_regex_values(*, values: list[str], prompt_text: str) -> list[str]:
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


def guardrail_rule_denial_reason(rule: RuntimeGuardrailRuleInput) -> str:
    if rule.effect == "allow":
        return f"{rule.rule_type}_allowlist_miss"
    return f"{rule.rule_type}_{rule.effect}"


def _readonly_evaluation(
    *,
    rule: RuntimeGuardrailRuleInput,
    assignment_ref: RuntimeGuardrailAssignmentRef | None,
    applicability_matched: bool,
    detector_evaluated: bool,
    matched_values: list[str],
    denied: bool,
    decision: str,
) -> GuardrailReadonlyEvaluation:
    reason_code = guardrail_rule_denial_reason(rule) if denied else None
    return GuardrailReadonlyEvaluation(
        policy_id=rule.policy_ref.policy_id,
        policy_revision_id=rule.policy_ref.policy_revision_id,
        rule_id=rule.rule_ref.rule_id,
        assignment_id=assignment_ref.assignment_id if assignment_ref else None,
        assignment_mode=assignment_ref.assignment_mode if assignment_ref else None,
        policy_name=rule.policy_ref.policy_name,
        policy_revision_number=rule.policy_ref.policy_revision_number,
        rule_name=rule.rule_ref.rule_name,
        assignment_scope_label=assignment_ref.assignment_scope_label if assignment_ref else None,
        phase=rule.phase,
        rule_type=rule.rule_type,
        effect=rule.effect,
        applicability_matched=applicability_matched,
        detector_evaluated=detector_evaluated,
        matched_values=matched_values,
        denied=denied,
        decision=decision,
        reason_code=reason_code,
        message=_guardrail_message(rule=rule) if denied else None,
        draft_ref=rule.rule_ref.draft_ref or rule.policy_ref.draft_ref,
    )


def _effective_assignment_ref(
    assignments: list[RuntimeGuardrailAssignmentRef],
) -> RuntimeGuardrailAssignmentRef | None:
    enforce_assignment = next(
        (assignment for assignment in assignments if assignment.assignment_mode == "enforce"),
        None,
    )
    return enforce_assignment or (assignments[0] if assignments else None)


def _guardrail_decision(
    *,
    rule: RuntimeGuardrailRuleInput,
    assignment_ref: RuntimeGuardrailAssignmentRef | None,
    denied: bool,
) -> str:
    if not denied:
        return "allowed"
    if rule.policy_ref.enforcement_mode == "monitor" or (
        assignment_ref is not None and assignment_ref.assignment_mode == "dry_run"
    ):
        return "would_block"
    return "blocked"


def _guardrail_message(*, rule: RuntimeGuardrailRuleInput) -> str:
    rule_label = "allowlist" if rule.effect == "allow" else rule.rule_type
    return f"{rule.phase} blocked by guardrail {rule_label} rule"


def _has_detector_input(context: GuardrailEvaluationContext) -> bool:
    return bool(context.response_text if context.phase == "response" else context.prompt_text)


_logger = structlog.get_logger(__name__)
GUARDRAIL_SCAN_CHAR_LIMIT = 65_536
GUARDRAIL_REGEX_TIMEOUT_SECONDS = 1.0
