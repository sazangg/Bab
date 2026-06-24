from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.gateway.types import GuardrailResolvedAccess
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.errors import GuardrailDeniedError
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.providers.schemas import ProviderChatCompletionRequest
from app.modules.usage import facade as usage_facade

GatewayGuardrailDenied = GuardrailDeniedError


def build_guardrail_context(
    *,
    resolved: GuardrailResolvedAccess,
    provider_payload: ProviderChatCompletionRequest,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
) -> GuardrailEvaluationContext:
    return GuardrailEvaluationContext(
        org_id=resolved.org_id,
        team_id=resolved.team_id,
        project_id=resolved.project_id,
        virtual_key_id=resolved.virtual_key_id,
        provider_id=resolved.provider_id,
        pool_id=resolved.pool_id,
        provider_model_offering_id=resolved.model_offering_id,
        public_model_id=resolved.public_model_id,
        public_model_name=resolved.public_model_name,
        route_candidate_id=resolved.route_candidate_id,
        gateway_endpoint=gateway_endpoint,
        request_id=current_request_id(),
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        requested_model=resolved.requested_model,
        provider_model=resolved.provider_model,
        prompt_text=_messages_text(provider_payload.messages),
    )


async def has_enforced_response_guardrails(
    *,
    context: GuardrailEvaluationContext,
    db: AsyncSession,
) -> bool:
    return await guardrails_facade.has_enforced_response_guardrails(
        context=context,
        db=db,
    )


async def evaluate_request_guardrails(
    *,
    context: GuardrailEvaluationContext,
    resolved: GuardrailResolvedAccess,
    db: AsyncSession,
) -> None:
    try:
        evaluated = await guardrails_facade.evaluate_request(context=context, db=db)
    except GuardrailDeniedError as exc:
        await record_gateway_guardrail_decision(
            context=context,
            resolved=resolved,
            stage="request_guardrail",
            outcome="denied",
            effective_action="deny",
            reason_code="guardrail_denied",
            message=exc.detail,
            policy_id=exc.policy_id,
            policy_revision_id=exc.policy_revision_id,
            assignment_id=exc.assignment_id,
            assignment_mode=exc.assignment_mode,
            assignment_scope_type=exc.assignment_scope_type,
            assignment_team_id=exc.assignment_team_id,
            assignment_project_id=exc.assignment_project_id,
            assignment_virtual_key_id=exc.assignment_virtual_key_id,
            rule_id=exc.rule_id,
            db=db,
        )
        raise
    if evaluated:
        for trace in evaluated.would_deny:
            await record_gateway_guardrail_decision(
                context=context,
                resolved=resolved,
                stage="request_guardrail",
                outcome="would_deny",
                effective_action="would_deny",
                reason_code=trace.reason_code,
                message=trace.message,
                policy_id=trace.policy_id,
                policy_revision_id=trace.policy_revision_id,
                assignment_id=trace.assignment_id,
                assignment_mode=trace.assignment_mode,
                assignment_scope_type=trace.assignment_scope_type,
                assignment_team_id=trace.assignment_team_id,
                assignment_project_id=trace.assignment_project_id,
                assignment_virtual_key_id=trace.assignment_virtual_key_id,
                rule_id=trace.rule_id,
                db=db,
            )
        await record_gateway_guardrail_decision(
            context=context,
            resolved=resolved,
            stage="request_guardrail",
            outcome="allowed",
            effective_action="allow",
            reason_code="request_guardrails_passed",
            message=None,
            policy_id=None,
            policy_revision_id=None,
            assignment_id=None,
            assignment_mode=None,
            assignment_scope_type=None,
            assignment_team_id=None,
            assignment_project_id=None,
            assignment_virtual_key_id=None,
            rule_id=None,
            db=db,
        )


async def evaluate_response_guardrails(
    *,
    context: GuardrailEvaluationContext,
    resolved: GuardrailResolvedAccess,
    response_text: str,
    db: AsyncSession,
) -> None:
    response_context = context.model_copy(update={"phase": "response"})
    try:
        evaluated = await guardrails_facade.evaluate_response(
            context=context,
            response_text=response_text,
            db=db,
        )
    except GuardrailDeniedError as exc:
        await record_gateway_guardrail_decision(
            context=response_context,
            resolved=resolved,
            stage="response_guardrail",
            outcome="denied",
            effective_action="deny",
            reason_code="guardrail_output_denied",
            message=exc.detail,
            policy_id=exc.policy_id,
            policy_revision_id=exc.policy_revision_id,
            assignment_id=exc.assignment_id,
            assignment_mode=exc.assignment_mode,
            assignment_scope_type=exc.assignment_scope_type,
            assignment_team_id=exc.assignment_team_id,
            assignment_project_id=exc.assignment_project_id,
            assignment_virtual_key_id=exc.assignment_virtual_key_id,
            rule_id=exc.rule_id,
            db=db,
        )
        raise
    if evaluated:
        for trace in evaluated.would_deny:
            await record_gateway_guardrail_decision(
                context=response_context,
                resolved=resolved,
                stage="response_guardrail",
                outcome="would_deny",
                effective_action="would_deny",
                reason_code=trace.reason_code,
                message=trace.message,
                policy_id=trace.policy_id,
                policy_revision_id=trace.policy_revision_id,
                assignment_id=trace.assignment_id,
                assignment_mode=trace.assignment_mode,
                assignment_scope_type=trace.assignment_scope_type,
                assignment_team_id=trace.assignment_team_id,
                assignment_project_id=trace.assignment_project_id,
                assignment_virtual_key_id=trace.assignment_virtual_key_id,
                rule_id=trace.rule_id,
                db=db,
            )
        await record_gateway_guardrail_decision(
            context=response_context,
            resolved=resolved,
            stage="response_guardrail",
            outcome="allowed",
            effective_action="allow",
            reason_code="response_guardrails_passed",
            message=None,
            policy_id=None,
            policy_revision_id=None,
            assignment_id=None,
            assignment_mode=None,
            assignment_scope_type=None,
            assignment_team_id=None,
            assignment_project_id=None,
            assignment_virtual_key_id=None,
            rule_id=None,
            db=db,
        )


async def record_gateway_guardrail_decision(
    *,
    context: GuardrailEvaluationContext,
    resolved: GuardrailResolvedAccess,
    stage: str,
    outcome: str,
    effective_action: str,
    reason_code: str,
    message: str | None,
    policy_id: UUID | None,
    policy_revision_id: UUID | None,
    assignment_id: UUID | None,
    assignment_mode: str | None,
    assignment_scope_type: str | None,
    assignment_team_id: UUID | None,
    assignment_project_id: UUID | None,
    assignment_virtual_key_id: UUID | None,
    rule_id: UUID | None,
    db: AsyncSession,
) -> None:
    if context.gateway_request_id is None:
        return
    shared_policy_id = policy_id
    if policy_id is not None:
        policy = await guardrails_repository.get_policy(
            policy_id=policy_id,
            org_id=resolved.org_id,
            db=db,
        )
        if policy is not None and policy.policy_id is not None:
            shared_policy_id = policy.policy_id
    await usage_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": context.gateway_request_id,
            "route_attempt_id": context.route_attempt_id,
            "decision_type": "guardrail",
            "stage": stage,
            "outcome": outcome,
            "effective_action": effective_action,
            "enforced": outcome != "would_deny",
            "policy_id": shared_policy_id,
            "policy_revision_id": policy_revision_id,
            "assignment_id": assignment_id,
            "assignment_mode": assignment_mode,
            "assignment_scope_type": assignment_scope_type,
            "assignment_team_id": assignment_team_id,
            "assignment_project_id": assignment_project_id,
            "assignment_virtual_key_id": assignment_virtual_key_id,
            "rule_id": rule_id,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": reason_code,
            "message": message,
            "dimension_snapshot": {
                "phase": context.phase,
                "virtual_key_id": str(resolved.virtual_key_id),
                "public_model_id": str(resolved.public_model_id),
                "provider_id": str(resolved.provider_id),
                "pool_id": str(resolved.pool_id),
                "route_candidate_id": str(resolved.route_candidate_id),
            },
            "metadata_": {
                "guardrail_policy_revision_id": str(policy_revision_id)
                if policy_revision_id
                else None,
                "legacy_guardrail_rule_id": str(rule_id) if rule_id else None,
                "requested_model": context.requested_model,
                "provider_model": context.provider_model,
            },
        },
        db=db,
    )


def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_content_to_text(part) for part in content)
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return str(content)
