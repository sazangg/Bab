from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.evaluation import (
    RuntimeGuardrailAssignmentRef,
    RuntimeGuardrailPolicyRef,
    RuntimeGuardrailRuleInput,
    RuntimeGuardrailRuleRef,
    RuntimeMatcherInput,
    evaluate_guardrail_rules_readonly,
)
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys.errors import VirtualKeyNotFoundError
from app.modules.keys.internal import repository as keys_repository
from app.modules.keys.internal.models import Project
from app.modules.keys.schemas import ResolvedLimitPolicy
from app.modules.policies.draft_validation import validate_policy_simulation_drafts
from app.modules.policies.errors import PolicyPermissionError, PolicyValidationError
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.runtime_limits import (
    RuntimeLimitEvaluationInput,
    evaluate_runtime_limits_readonly,
)
from app.modules.policies.schemas import (
    PolicySimulationDecision,
    PolicySimulationDraft,
    PolicySimulationGuardrailResult,
    PolicySimulationLimitResult,
    PolicySimulationRequest,
    PolicySimulationResponse,
    PolicySimulationRouteAttempt,
    PolicySimulationSubject,
    PolicySimulationWarning,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.registry import default_cost_calculator_registry


@dataclass(frozen=True)
class _SimulationTarget:
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    virtual_key_name: str | None


@dataclass(frozen=True)
class _ReplacementPolicy:
    concrete_id: UUID
    shared_policy_id: UUID | None


@dataclass(frozen=True)
class _ReplacementIndex:
    access: dict[UUID, _ReplacementPolicy]
    limit: dict[UUID, _ReplacementPolicy]
    guardrail: dict[UUID, _ReplacementPolicy]


@dataclass(frozen=True)
class _SimulationRouteContext:
    org_id: UUID
    team_id: UUID
    project_id: UUID
    access_policy_id: UUID | None
    access_policy_revision_id: UUID | None
    access_policy_assignment_id: UUID | None
    access_policy_route_id: UUID | None
    public_model_id: UUID | None
    route_candidate_id: UUID | None
    primary_route_candidate_id: UUID | None
    public_model_name: str | None
    routing_mode: str | None
    model_offering_id: UUID
    limit_policy_ids: list[UUID]
    limit_policies: list[ResolvedLimitPolicy]
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None
    fallback_disabled_reason: str | None
    draft_ref: str | None = None

    def model_copy(self, *, update: dict[str, Any]) -> "_SimulationRouteContext":
        values = self.__dict__ | update
        return _SimulationRouteContext(**values)


@dataclass(frozen=True)
class _AccessAssignmentRef:
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    assignment_id: UUID | None
    policy_id: UUID | None
    access_policy_id: UUID | None
    draft: PolicySimulationDraft | None = None


@dataclass(frozen=True)
class _AccessPublicModelRef:
    public_model_id: UUID | None
    access_policy_id: UUID | None
    access_policy_revision_id: UUID | None
    public_model_name: str
    routing_mode: str
    fallback_on: list[str]
    max_route_attempts: int | None
    created_at: datetime | None


@dataclass(frozen=True)
class _AccessCandidateRef:
    public_model: _AccessPublicModelRef
    assignment: _AccessAssignmentRef
    route_candidate_id: UUID | None
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_id: UUID
    priority: int
    weight: int
    created_at: datetime | None
    draft_ref: str | None = None


@dataclass(frozen=True)
class _AccessResolution:
    route_attempts: list[PolicySimulationRouteAttempt]
    decisions: list[PolicySimulationDecision]
    resolved_attempts: list[tuple[UUID | None, _SimulationRouteContext, bool]]
    access_denied_reason: str | None
    public_model_name: str | None
    routing_mode: str | None
    fallback_on: list[str]
    provider_pinned: bool
    fallback_disabled_reason: str | None


async def simulate_active_policies(
    *,
    org_id,
    payload: PolicySimulationRequest,
    actor: AuthenticatedUser | None,
    db: AsyncSession,
) -> PolicySimulationResponse:
    validate_policy_simulation_drafts(payload.drafts)
    target = await _resolve_simulation_target(
        org_id=org_id,
        virtual_key_id=payload.target.virtual_key_id,
        db=db,
    )
    await _authorize_simulation(actor=actor, target=target, payload=payload, db=db)
    replacement_index = await _validate_replacement_drafts(
        org_id=org_id,
        payload=payload,
        actor=actor,
        target=target,
        db=db,
    )
    warnings: list[PolicySimulationWarning] = []
    access_resolution = await _simulate_access_resolution(
        target=target,
        payload=payload,
        replacement_index=replacement_index,
        db=db,
    )
    subject = _simulation_subject(
        payload=payload,
        target=target,
        first_attempt=access_resolution.route_attempts[0]
        if access_resolution.route_attempts
        else None,
    )
    route_attempts = access_resolution.route_attempts
    decisions = access_resolution.decisions

    if access_resolution.access_denied_reason is not None:
        decisions.append(
            PolicySimulationDecision(
                decision_type="access",
                stage="access_resolution",
                outcome="denied",
                effective_action="deny",
                enforced=True,
                reason_code=access_resolution.access_denied_reason,
                message="access policy denied the requested model",
            )
        )
        return PolicySimulationResponse(
            subject=subject,
            final_decision="deny",
            denied_stage="access_resolution",
            denied_reason=access_resolution.access_denied_reason,
            requested_model=payload.requested_model,
            route_attempts=route_attempts,
            decisions=decisions,
            warnings=warnings,
        )
    final_decision = "allow"
    denied_stage = None
    denied_reason = None
    limit_results: list[PolicySimulationLimitResult] = []
    guardrail_results: list[PolicySimulationGuardrailResult] = []

    if (
        payload.provider_id is not None
        and access_resolution.fallback_disabled_reason == "provider_pinned"
    ):
        warnings.append(
            PolicySimulationWarning(
                code="provider_pinned_disables_fallback",
                message="Provider pinning disables fallback route attempts.",
            )
        )
    if (
        payload.streaming
        and access_resolution.fallback_disabled_reason == "streaming_fallback_phase_2"
    ):
        warnings.append(
            PolicySimulationWarning(
                code="streaming_fallback_phase_2",
                message="Streaming requests only simulate the selected route attempt.",
            )
        )
    if not access_resolution.resolved_attempts:
        warnings.append(
            PolicySimulationWarning(
                code="no_fallback_candidates",
                message="No route candidate would be attempted.",
            )
        )

    resolved_attempts = access_resolution.resolved_attempts
    if payload.include_limits:
        for route_candidate_id, resolved, is_primary_attempt in resolved_attempts:
            resolved = await _resolved_with_limit_drafts(
                payload=payload,
                resolved=resolved,
                warnings=warnings,
                target=target,
                replacement_index=replacement_index,
                db=db,
            )
            evaluation = await evaluate_runtime_limits_readonly(
                payload=RuntimeLimitEvaluationInput(
                    resolved=resolved,
                    estimated_input_tokens=payload.estimated_input_tokens,
                    requested_output_tokens=payload.requested_output_tokens,
                    estimated_cost_cents=_estimated_cost_cents(payload=payload, resolved=resolved),
                    estimated_cost_micro_cents=_estimated_cost_micro_cents(
                        payload=payload,
                        resolved=resolved,
                    ),
                    gateway_endpoint=payload.gateway_endpoint,
                ),
                db=db,
            )
            for result in evaluation.results:
                limit_results.append(
                    PolicySimulationLimitResult(
                        route_candidate_id=route_candidate_id,
                        policy_id=result.limit.limit_policy_id,
                        policy_name=result.limit.limit_policy_name,
                        policy_revision_id=result.limit.limit_policy_revision_id,
                        rule_id=result.limit.limit_policy_rule_id,
                        rule_name=result.limit.name,
                        assignment_id=result.limit.limit_policy_assignment_id,
                        limit_type=result.limit.limit_type,
                        limit_value=result.limit.limit_value,
                        interval_unit=result.limit.interval_unit,
                        interval_count=result.limit.interval_count,
                        counter_key=result.counter_key,
                        counting_unit=result.counting_unit,
                        window_descriptor=result.window_descriptor,
                        current_usage=result.current_usage,
                        active_reserved_usage=result.active_reserved_usage,
                        attempted_usage=result.attempted_usage,
                        would_deny=result.would_deny,
                        reason_code=result.reason_code,
                        message=result.message,
                        draft_ref=result.limit.draft_ref,
                    )
                )
            if is_primary_attempt and evaluation.denial is not None:
                final_decision = "deny"
                denied_stage = "limit_reservation"
                denied_reason = evaluation.denial.reason_code
                decisions.append(
                    PolicySimulationDecision(
                        decision_type="limit",
                        stage="limit_reservation",
                        outcome="denied",
                        effective_action="deny",
                        enforced=True,
                        policy_id=evaluation.denial.limit.limit_policy_id,
                        policy_name=evaluation.denial.limit.limit_policy_name,
                        policy_kind="limit",
                        policy_revision_id=evaluation.denial.limit.limit_policy_revision_id,
                        assignment_id=evaluation.denial.limit.limit_policy_assignment_id,
                        rule_id=evaluation.denial.limit.limit_policy_rule_id,
                        rule_name=evaluation.denial.limit.name,
                        reason_code=evaluation.denial.reason_code,
                        message=evaluation.denial.message,
                        dimension_snapshot=evaluation.dimension_snapshot,
                        draft_ref=evaluation.denial.limit.draft_ref,
                    )
                )

    if payload.include_guardrails:
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
        for route_candidate_id, resolved, is_primary_attempt in resolved_attempts:
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
                    guardrail_results.append(
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

    return PolicySimulationResponse(
        subject=subject,
        final_decision=final_decision,
        denied_stage=denied_stage,
        denied_reason=denied_reason,
        requested_model=payload.requested_model,
        public_model_name=access_resolution.public_model_name,
        routing_mode=access_resolution.routing_mode,
        fallback_on=access_resolution.fallback_on,
        provider_pinned=access_resolution.provider_pinned,
        fallback_disabled_reason=access_resolution.fallback_disabled_reason,
        route_attempts=route_attempts,
        decisions=decisions,
        limit_results=limit_results,
        guardrail_results=guardrail_results,
        warnings=warnings,
    )


def _simulation_subject(
    *,
    payload: PolicySimulationRequest,
    target: _SimulationTarget,
    first_attempt: PolicySimulationRouteAttempt | None,
) -> PolicySimulationSubject:
    return PolicySimulationSubject(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        virtual_key_name=target.virtual_key_name,
        requested_model=payload.requested_model,
        gateway_endpoint=payload.gateway_endpoint,
        streaming=payload.streaming,
        provider_id=payload.provider_id
        or (first_attempt.provider_id if first_attempt else None),
    )


async def _resolve_simulation_target(
    *, org_id: UUID, virtual_key_id: UUID, db: AsyncSession
) -> _SimulationTarget:
    virtual_key = await keys_repository.get_virtual_key_by_id(
        org_id=org_id,
        key_id=virtual_key_id,
        db=db,
    )
    now = datetime.now(UTC)
    if virtual_key is None or virtual_key.revoked_at is not None:
        raise VirtualKeyNotFoundError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= now:
        raise VirtualKeyNotFoundError
    project = await db.get(Project, virtual_key.project_id)
    if project is None or project.org_id != org_id or not project.is_active:
        raise VirtualKeyNotFoundError
    team = await db.get(Team, project.team_id)
    if team is None or team.org_id != org_id or not team.is_active:
        raise VirtualKeyNotFoundError
    return _SimulationTarget(
        org_id=org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        virtual_key_name=virtual_key.name,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _validate_replacement_drafts(
    *,
    org_id: UUID,
    payload: PolicySimulationRequest,
    actor: AuthenticatedUser | None,
    target: _SimulationTarget,
    db: AsyncSession,
) -> _ReplacementIndex:
    access: dict[UUID, _ReplacementPolicy] = {}
    limit: dict[UUID, _ReplacementPolicy] = {}
    guardrail: dict[UUID, _ReplacementPolicy] = {}
    for draft in payload.drafts:
        if draft.operation != "replace_policy" or draft.existing_policy_id is None:
            continue
        if draft.kind == "access":
            policy = await policies_repository.get_access_policy(
                policy_id=draft.existing_policy_id,
                org_id=org_id,
                db=db,
            )
            if policy is None or not policy.is_active:
                if _is_scoped_actor(actor):
                    raise PolicyPermissionError
                raise PolicyValidationError
            if not await _can_replace_policy(
                actor=actor,
                target=target,
                policy=policy,
                kind="access",
                db=db,
            ):
                raise PolicyPermissionError
            access[draft.existing_policy_id] = _ReplacementPolicy(
                concrete_id=policy.id,
                shared_policy_id=policy.policy_id,
            )
            continue
        if draft.kind == "limit":
            policy = await policies_repository.get_limit_policy(
                policy_id=draft.existing_policy_id,
                org_id=org_id,
                db=db,
            )
            if policy is None or not policy.is_active:
                if _is_scoped_actor(actor):
                    raise PolicyPermissionError
                raise PolicyValidationError
            if not await _can_replace_policy(
                actor=actor,
                target=target,
                policy=policy,
                kind="limit",
                db=db,
            ):
                raise PolicyPermissionError
            limit[draft.existing_policy_id] = _ReplacementPolicy(
                concrete_id=policy.id,
                shared_policy_id=policy.policy_id,
            )
            continue
        policy = await guardrails_repository.get_policy(
            policy_id=draft.existing_policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is None or not policy.is_active:
            if _is_scoped_actor(actor):
                raise PolicyPermissionError
            raise PolicyValidationError
        if not await _can_replace_guardrail_policy(
            actor=actor,
            target=target,
            policy=policy,
            db=db,
        ):
            raise PolicyPermissionError
        guardrail[draft.existing_policy_id] = _ReplacementPolicy(
            concrete_id=policy.id,
            shared_policy_id=policy.policy_id,
        )
    return _ReplacementIndex(access=access, limit=limit, guardrail=guardrail)


async def _authorize_simulation(
    *,
    actor: AuthenticatedUser | None,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    db: AsyncSession,
) -> None:
    if actor is None:
        return
    if actor.org_id != target.org_id:
        raise PolicyPermissionError
    scoped_admin = _is_target_scoped_admin(actor=actor, target=target)
    if not (_has_org_permission(actor, "policies.view") or scoped_admin):
        raise PolicyPermissionError
    guardrail_requested = payload.include_guardrails or any(
        draft.kind == "guardrail" for draft in payload.drafts
    )
    if guardrail_requested and not (
        _has_org_permission(actor, "guardrails.view") or scoped_admin
    ):
        raise PolicyPermissionError
    for draft in payload.drafts:
        if draft.assignment is None:
            continue
        if not await _can_simulate_draft_assignment(
            actor=actor,
            target=target,
            assignment=draft.assignment,
            db=db,
        ):
            raise PolicyPermissionError


def _has_org_permission(actor: AuthenticatedUser, permission: str) -> bool:
    return "*" in actor.permissions or permission in actor.permissions


def _is_scoped_actor(actor: AuthenticatedUser | None) -> bool:
    if actor is None:
        return False
    if actor.role in {"org_owner", "org_admin"} or _has_org_permission(actor, "policies.view"):
        return False
    return True


async def _can_replace_policy(
    *,
    actor: AuthenticatedUser | None,
    target: _SimulationTarget,
    policy,
    kind: str,
    db: AsyncSession,
) -> bool:
    if actor is None:
        return True
    if actor.role in {"org_owner", "org_admin"} or _has_org_permission(actor, "policies.view"):
        return True
    if _policy_owned_in_actor_scope(actor=actor, policy=policy, target=target):
        return True
    assignments = (
        await policies_repository.list_policy_assignments_for_access_policy(
            org_id=target.org_id,
            access_policy_id=policy.id,
            active_only=True,
            db=db,
        )
        if kind == "access"
        else await policies_repository.list_policy_assignments_for_limit_policy(
            org_id=target.org_id,
            limit_policy_id=policy.id,
            active_only=True,
            db=db,
        )
    )
    for assignment in assignments:
        if await _assignment_visible_to_actor(
            actor=actor,
            target=target,
            assignment=assignment,
            db=db,
        ):
            return True
    return False


async def _can_replace_guardrail_policy(
    *,
    actor: AuthenticatedUser | None,
    target: _SimulationTarget,
    policy,
    db: AsyncSession,
) -> bool:
    if actor is None:
        return True
    if actor.role in {"org_owner", "org_admin"} or _has_org_permission(actor, "policies.view"):
        return True
    assignments = await guardrails_repository.list_policy_assignments(
        org_id=target.org_id,
        policy_id=policy.id,
        active_only=True,
        db=db,
    )
    for assignment in assignments:
        if await _assignment_visible_to_actor(
            actor=actor,
            target=target,
            assignment=assignment,
            db=db,
        ):
            return True
    return False


def _policy_owned_in_actor_scope(
    *, actor: AuthenticatedUser, policy, target: _SimulationTarget
) -> bool:
    if policy.owning_scope_type == "team":
        return any(
            membership.team_id == policy.owning_team_id and membership.role == "team_admin"
            for membership in actor.team_memberships
        )
    if policy.owning_scope_type == "project":
        return any(
            membership.project_id == policy.owning_project_id
            and membership.role == "project_admin"
            for membership in actor.project_memberships
        ) or (
            policy.owning_team_id is not None
            and any(
                membership.team_id == policy.owning_team_id and membership.role == "team_admin"
                for membership in actor.team_memberships
            )
        )
    if policy.owning_scope_type == "virtual_key":
        return policy.owning_virtual_key_id == target.virtual_key_id and _is_target_scoped_admin(
            actor=actor,
            target=target,
        )
    return False


async def _assignment_visible_to_actor(
    *, actor: AuthenticatedUser, target: _SimulationTarget, assignment, db: AsyncSession
) -> bool:
    if assignment.scope_type == "org":
        return False
    if assignment.scope_type == "team":
        return any(
            membership.team_id == assignment.team_id and membership.role == "team_admin"
            for membership in actor.team_memberships
        )
    if assignment.scope_type == "project":
        if any(
            membership.project_id == assignment.project_id and membership.role == "project_admin"
            for membership in actor.project_memberships
        ):
            return True
        project = await db.get(Project, assignment.project_id)
        return project is not None and any(
            membership.team_id == project.team_id and membership.role == "team_admin"
            for membership in actor.team_memberships
        )
    if assignment.scope_type == "virtual_key":
        virtual_key = await keys_repository.get_virtual_key_by_id(
            org_id=target.org_id,
            key_id=assignment.virtual_key_id,
            db=db,
        )
        if virtual_key is None:
            return False
        project = await db.get(Project, virtual_key.project_id)
        if project is None:
            return False
        return any(
            membership.project_id == project.id and membership.role == "project_admin"
            for membership in actor.project_memberships
        ) or any(
            membership.team_id == project.team_id and membership.role == "team_admin"
            for membership in actor.team_memberships
        )
    return False


async def _can_simulate_draft_assignment(
    *,
    actor: AuthenticatedUser,
    target: _SimulationTarget,
    assignment,
    db: AsyncSession,
) -> bool:
    if actor.role in {"org_owner", "org_admin"} or _has_org_permission(actor, "policies.view"):
        return True
    team_admin_team_ids = {
        membership.team_id
        for membership in actor.team_memberships
        if membership.role == "team_admin"
    }
    project_admin_project_ids = {
        membership.project_id
        for membership in actor.project_memberships
        if membership.role == "project_admin"
    }
    if assignment.scope_type == "org":
        return False
    if assignment.scope_type == "team":
        return assignment.team_id in team_admin_team_ids
    if assignment.scope_type == "project":
        if assignment.project_id in project_admin_project_ids:
            return True
        project = await db.get(Project, assignment.project_id)
        return (
            project is not None
            and project.org_id == target.org_id
            and project.team_id in team_admin_team_ids
        )
    if assignment.scope_type == "virtual_key":
        virtual_key = await keys_repository.get_virtual_key_by_id(
            org_id=target.org_id,
            key_id=assignment.virtual_key_id,
            db=db,
        )
        if virtual_key is None or virtual_key.revoked_at is not None:
            return False
        project = await db.get(Project, virtual_key.project_id)
        if project is None or project.org_id != target.org_id:
            return False
        return project.id in project_admin_project_ids or project.team_id in team_admin_team_ids
    return False


def _is_target_scoped_admin(*, actor: AuthenticatedUser, target: _SimulationTarget) -> bool:
    if actor.role in {"org_owner", "org_admin"}:
        return True
    if any(
        membership.team_id == target.team_id and membership.role == "team_admin"
        for membership in actor.team_memberships
    ):
        return True
    return any(
        membership.project_id == target.project_id and membership.role == "project_admin"
        for membership in actor.project_memberships
    )


async def _simulate_access_resolution(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> _AccessResolution:
    candidates = await _effective_access_candidates_with_drafts(
        target=target,
        payload=payload,
        replacement_index=replacement_index,
        db=db,
    )
    candidates.sort(
        key=lambda item: (
            item.priority,
            -item.weight,
            item.created_at is None,
            _sort_datetime(item.created_at),
        )
    )
    route_attempts: list[PolicySimulationRouteAttempt] = []
    decisions: list[PolicySimulationDecision] = []
    resolved_attempts: list[tuple[UUID | None, _SimulationRouteContext, bool]] = []
    matched_public_model_name: str | None = None
    selected_attempt: PolicySimulationRouteAttempt | None = None
    attempted_count = 0
    fallback_disabled_reason = None
    selected_public_model: _AccessPublicModelRef | None = None
    for candidate_index, candidate in enumerate(candidates):
        provider = pool = model = None
        try:
            provider = await providers_facade.get_provider(
                provider_id=candidate.provider_id,
                scope=Scope(org_id=target.org_id),
                db=db,
            )
            pool = await providers_facade.get_credential_pool(
                pool_id=candidate.credential_pool_id,
                scope=Scope(org_id=target.org_id),
                db=db,
            )
            model = await providers_facade.get_model_offering(
                model_offering_id=candidate.model_offering_id,
                scope=Scope(org_id=target.org_id),
                db=db,
            )
        except ProviderNotFoundError:
            pass
        skipped_reason, skipped_message = _access_candidate_skip_reason(
            payload=payload,
            candidate=candidate,
            provider=provider,
            pool=pool,
            model=model,
            matched_public_model_name=matched_public_model_name,
        )
        would_attempt = skipped_reason is None
        if would_attempt and matched_public_model_name is None:
            matched_public_model_name = candidate.public_model.public_model_name
            selected_public_model = candidate.public_model
        if would_attempt and matched_public_model_name != candidate.public_model.public_model_name:
            would_attempt = False
            skipped_reason = "routing_mode_disables_fallback"
            skipped_message = "The selected routing mode did not attempt this route."
        if would_attempt and selected_public_model is not None:
            if selected_public_model.routing_mode == "single_route" and attempted_count > 0:
                would_attempt = False
            if payload.streaming and attempted_count > 0:
                would_attempt = False
                fallback_disabled_reason = "streaming_fallback_phase_2"
            if payload.provider_id is not None and attempted_count > 0:
                would_attempt = False
                fallback_disabled_reason = "provider_pinned"
            if (
                selected_public_model.max_route_attempts is not None
                and attempted_count >= selected_public_model.max_route_attempts
            ):
                would_attempt = False
            if not would_attempt and skipped_reason is None:
                skipped_reason = "routing_mode_disables_fallback"
                skipped_message = "The selected routing mode did not attempt this route."
        attempt_index = attempted_count if would_attempt else None
        selected = would_attempt and selected_attempt is None
        if would_attempt:
            attempted_count += 1
        attempt = PolicySimulationRouteAttempt(
            candidate_index=candidate_index,
            attempt_index=attempt_index,
            selected=selected,
            would_attempt=would_attempt,
            skipped_reason=skipped_reason,
            skipped_message=skipped_message,
            access_policy_id=candidate.public_model.access_policy_id,
            access_policy_revision_id=candidate.public_model.access_policy_revision_id,
            access_policy_assignment_id=candidate.assignment.assignment_id,
            public_model_id=candidate.public_model.public_model_id,
            route_candidate_id=candidate.route_candidate_id,
            public_model_name=candidate.public_model.public_model_name,
            routing_mode=candidate.public_model.routing_mode,
            provider_id=candidate.provider_id,
            provider_name=provider.name if provider else None,
            credential_pool_id=candidate.credential_pool_id,
            credential_pool_name=pool.name if pool else None,
            provider_model_offering_id=model.id if model else candidate.model_offering_id,
            provider_model=model.provider_model_name if model else None,
            input_price_per_million_tokens=(
                model.effective_input_price_per_million_tokens if model else None
            ),
            output_price_per_million_tokens=(
                model.effective_output_price_per_million_tokens if model else None
            ),
            draft_ref=candidate.draft_ref,
        )
        route_attempts.append(attempt)
        decisions.append(_routing_decision_from_attempt(attempt))
        if would_attempt:
            context = await _route_context_from_access_attempt(
                target=target,
                payload=payload,
                attempt=attempt,
                fallback_disabled_reason=fallback_disabled_reason,
                db=db,
            )
            resolved_attempts.append((attempt.route_candidate_id, context, selected))
        if selected:
            selected_attempt = attempt
    if selected_attempt is None:
        return _AccessResolution(
            route_attempts=route_attempts,
            decisions=decisions,
            resolved_attempts=[],
            access_denied_reason="no_matching_route",
            public_model_name=None,
            routing_mode=None,
            fallback_on=[],
            provider_pinned=payload.provider_id is not None,
            fallback_disabled_reason=fallback_disabled_reason,
        )
    attempts_to_evaluate = (
        resolved_attempts if payload.evaluate_all_route_candidates else resolved_attempts[:1]
    )
    return _AccessResolution(
        route_attempts=route_attempts,
        decisions=decisions,
        resolved_attempts=attempts_to_evaluate,
        access_denied_reason=None,
        public_model_name=selected_attempt.public_model_name,
        routing_mode=selected_attempt.routing_mode,
        fallback_on=selected_public_model.fallback_on if selected_public_model else [],
        provider_pinned=payload.provider_id is not None,
        fallback_disabled_reason=fallback_disabled_reason,
    )


async def _effective_access_candidates_with_drafts(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> list[_AccessCandidateRef]:
    saved_assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        policy_type="access",
        db=db,
    )
    replacement_drafts = {
        draft.existing_policy_id: (draft_index, draft)
        for draft_index, draft in enumerate(payload.drafts)
        if draft.kind == "access"
        and draft.operation == "replace_policy"
        and draft.existing_policy_id is not None
    }
    effective: list[_AccessCandidateRef] | None = None
    for scope_type in ("org", "team", "project", "virtual_key"):
        scope_saved_assignments = [
            assignment for assignment in saved_assignments if assignment.scope_type == scope_type
        ]
        scope_has_source = bool(scope_saved_assignments) or _draft_access_scope_has_source(
            target=target,
            payload=payload,
            scope_type=scope_type,
        )
        scoped: list[_AccessCandidateRef] = []
        scoped.extend(
            await _saved_access_candidates_for_scope(
                org_id=target.org_id,
                assignments=scope_saved_assignments,
                replacement_drafts=replacement_drafts,
                replacement_index=replacement_index,
                db=db,
            )
        )
        scoped.extend(
            _draft_access_candidates_for_scope(
                target=target,
                payload=payload,
                scope_type=scope_type,
                replacement_index=replacement_index,
            )
        )
        if not scope_has_source:
            continue
        if effective is None:
            effective = scoped
            continue
        effective = [
            candidate
            for candidate in scoped
            if any(_access_candidate_matches(candidate, ancestor) for ancestor in effective)
        ]
    return effective or []


def _draft_access_scope_has_source(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    scope_type: str,
) -> bool:
    for draft in payload.drafts:
        if draft.kind != "access" or draft.access_policy is None or draft.assignment is None:
            continue
        if draft.assignment.scope_type != scope_type:
            continue
        if _draft_assignment_matches_target(draft=draft, target=target):
            return True
    return False


async def _saved_access_candidates_for_scope(
    *,
    org_id: UUID,
    assignments: list,
    replacement_drafts: dict[UUID | None, tuple[int, PolicySimulationDraft]],
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> list[_AccessCandidateRef]:
    candidates: list[_AccessCandidateRef] = []
    for assignment in assignments:
        replacement_item = None
        for draft_id, item in replacement_drafts.items():
            replacement = replacement_index.access.get(draft_id)
            if replacement is None:
                continue
            if (
                assignment.access_policy_id == replacement.concrete_id
                or assignment.policy_id == replacement.shared_policy_id
            ):
                replacement_item = item
                break
        assignment_ref = _assignment_ref_from_saved(assignment)
        if replacement_item is not None:
            draft_index, draft = replacement_item
            assert draft.access_policy is not None
            candidates.extend(
                _access_candidates_from_draft_policy(
                    draft=draft,
                    draft_index=draft_index,
                    assignment=assignment_ref,
                    access_policy_id=assignment.policy_id,
                )
            )
            continue
        candidates.extend(
            await _access_candidates_from_saved_assignment(
                org_id=org_id,
                assignment=assignment,
                assignment_ref=assignment_ref,
                db=db,
            )
        )
    return candidates


async def _access_candidates_from_saved_assignment(
    *,
    org_id: UUID,
    assignment,
    assignment_ref: _AccessAssignmentRef,
    db: AsyncSession,
) -> list[_AccessCandidateRef]:
    if assignment.policy_id is not None:
        policy = await policies_repository.get_policy(
            policy_id=assignment.policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is None or policy.kind != "access" or not policy.is_active:
            return []
        revision = await policies_repository.get_active_policy_revision(
            org_id=org_id,
            policy_id=policy.id,
            db=db,
        )
        if revision is None:
            return []
        public_models = await policies_repository.list_access_policy_revision_public_models(
            org_id=org_id,
            policy_revision_id=revision.id,
            db=db,
        )
    elif assignment.access_policy_id is not None:
        policy = await policies_repository.get_access_policy(
            policy_id=assignment.access_policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is None or policy.policy_id is None or not policy.is_active:
            return []
        public_models = await policies_repository.list_access_policy_public_models(
            org_id=org_id,
            access_policy_id=policy.id,
            db=db,
        )
    else:
        return []
    candidates: list[_AccessCandidateRef] = []
    for public_model in public_models:
        if not public_model.is_active:
            continue
        public_model_ref = _AccessPublicModelRef(
            public_model_id=public_model.id,
            access_policy_id=public_model.access_policy_id or assignment.policy_id,
            access_policy_revision_id=public_model.policy_revision_id,
            public_model_name=public_model.public_model_name,
            routing_mode=public_model.routing_mode,
            fallback_on=public_model.fallback_on,
            max_route_attempts=public_model.max_route_attempts,
            created_at=public_model.created_at,
        )
        route_candidates = await policies_repository.list_access_policy_route_candidates(
            org_id=org_id,
            public_model_id=public_model.id,
            db=db,
        )
        candidates.extend(
            _AccessCandidateRef(
                public_model=public_model_ref,
                assignment=assignment_ref,
                route_candidate_id=candidate.id,
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_offering_id=candidate.provider_model_offering_id
                or candidate.model_offering_id,
                priority=candidate.priority,
                weight=candidate.weight,
                created_at=candidate.created_at,
            )
            for candidate in route_candidates
            if candidate.is_active
        )
    return candidates


def _draft_access_candidates_for_scope(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    scope_type: str,
    replacement_index: _ReplacementIndex,
) -> list[_AccessCandidateRef]:
    candidates: list[_AccessCandidateRef] = []
    for draft_index, draft in enumerate(payload.drafts):
        if draft.kind != "access" or draft.access_policy is None or draft.assignment is None:
            continue
        if draft.assignment.scope_type != scope_type:
            continue
        if not _draft_assignment_matches_target(draft=draft, target=target):
            continue
        replacement = (
            replacement_index.access.get(draft.existing_policy_id)
            if draft.existing_policy_id is not None
            else None
        )
        candidates.extend(
            _access_candidates_from_draft_policy(
                draft=draft,
                draft_index=draft_index,
                assignment=_assignment_ref_from_draft(draft),
                access_policy_id=(
                    replacement.shared_policy_id
                    if draft.operation == "replace_policy" and replacement is not None
                    else None
                ),
            )
        )
    return candidates


def _access_candidates_from_draft_policy(
    *,
    draft: PolicySimulationDraft,
    draft_index: int,
    assignment: _AccessAssignmentRef,
    access_policy_id: UUID | None,
) -> list[_AccessCandidateRef]:
    assert draft.access_policy is not None
    if not draft.access_policy.is_active:
        return []
    candidates: list[_AccessCandidateRef] = []
    for public_model_index, public_model in enumerate(draft.access_policy.public_models):
        if not public_model.is_active:
            continue
        public_model_ref = _AccessPublicModelRef(
            public_model_id=None,
            access_policy_id=access_policy_id,
            access_policy_revision_id=None,
            public_model_name=public_model.public_model_name,
            routing_mode=public_model.routing_mode,
            fallback_on=public_model.fallback_on,
            max_route_attempts=public_model.max_route_attempts,
            created_at=None,
        )
        for candidate_index, candidate in enumerate(public_model.candidates):
            if not candidate.is_active:
                continue
            candidates.append(
                _AccessCandidateRef(
                    public_model=public_model_ref,
                    assignment=assignment,
                    route_candidate_id=None,
                    provider_id=candidate.provider_id,
                    credential_pool_id=candidate.credential_pool_id,
                    model_offering_id=candidate.model_offering_id,
                    priority=candidate.priority,
                    weight=candidate.weight,
                    created_at=None,
                    draft_ref=(
                        f"draft[{draft_index}]:access_policy.public_models"
                        f"[{public_model_index}].candidates[{candidate_index}]"
                    ),
                )
            )
    return candidates


def _assignment_ref_from_saved(assignment) -> _AccessAssignmentRef:
    return _AccessAssignmentRef(
        scope_type=assignment.scope_type,
        team_id=assignment.team_id,
        project_id=assignment.project_id,
        virtual_key_id=assignment.virtual_key_id,
        assignment_id=assignment.id,
        policy_id=assignment.policy_id,
        access_policy_id=assignment.access_policy_id,
    )


def _assignment_ref_from_draft(draft: PolicySimulationDraft) -> _AccessAssignmentRef:
    assignment = draft.assignment
    assert assignment is not None
    return _AccessAssignmentRef(
        scope_type=assignment.scope_type,
        team_id=assignment.team_id,
        project_id=assignment.project_id,
        virtual_key_id=assignment.virtual_key_id,
        assignment_id=None,
        policy_id=None,
        access_policy_id=None,
        draft=draft,
    )


def _access_candidate_matches(
    child: _AccessCandidateRef,
    ancestor: _AccessCandidateRef,
) -> bool:
    return (
        child.public_model.public_model_name == ancestor.public_model.public_model_name
        and child.provider_id == ancestor.provider_id
        and child.credential_pool_id == ancestor.credential_pool_id
        and child.model_offering_id == ancestor.model_offering_id
    )


def _access_candidate_skip_reason(
    *,
    payload: PolicySimulationRequest,
    candidate: _AccessCandidateRef,
    provider,
    pool,
    model,
    matched_public_model_name: str | None,
) -> tuple[str | None, str | None]:
    if payload.requested_model != candidate.public_model.public_model_name:
        return "requested_model_mismatch", "The public model name did not match the request."
    if (
        matched_public_model_name is not None
        and matched_public_model_name != candidate.public_model.public_model_name
    ):
        return (
            "routing_mode_disables_fallback",
            "The selected routing mode did not attempt this route.",
        )
    if payload.provider_id is not None and candidate.provider_id != payload.provider_id:
        return "provider_pinned_mismatch", "The request pinned a different provider."
    if provider is None or not provider.is_active:
        return "provider_inactive", "The provider is inactive or missing."
    if pool is None or not pool.is_active or pool.provider_id != candidate.provider_id:
        return "credential_pool_inactive", "The credential pool is inactive or missing."
    if model is None or not model.is_active or model.provider_id != candidate.provider_id:
        return "provider_model_offering_inactive", "The model offering is inactive or missing."
    if not _provider_supports_gateway_endpoint(provider, payload.gateway_endpoint):
        return "endpoint_incompatible", "The provider does not support this gateway endpoint."
    return None, None


def _provider_supports_gateway_endpoint(provider, gateway_endpoint: str | None) -> bool:
    if gateway_endpoint is None:
        return True
    if gateway_endpoint == "anthropic_messages":
        return bool(provider.integration_capabilities.get("native_anthropic_messages"))
    if gateway_endpoint in {"chat_completions", "responses", "completions"}:
        return bool(provider.integration_capabilities.get("openai_compatible_chat"))
    return True


def _sort_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return _as_utc(value).isoformat()


def _routing_decision_from_attempt(
    attempt: PolicySimulationRouteAttempt,
) -> PolicySimulationDecision:
    outcome = "selected" if attempt.selected else "matched"
    if attempt.skipped_reason is not None:
        outcome = "skipped"
    return PolicySimulationDecision(
        decision_type="provider_routing",
        stage="access_resolution",
        outcome=outcome,
        enforced=False,
        policy_id=attempt.access_policy_id,
        policy_kind="access",
        policy_revision_id=attempt.access_policy_revision_id,
        assignment_id=attempt.access_policy_assignment_id,
        route_candidate_id=attempt.route_candidate_id,
        reason_code=attempt.skipped_reason,
        message=attempt.skipped_message,
        draft_ref=attempt.draft_ref,
    )


def _draft_assignment_matches_target(
    *, draft: PolicySimulationDraft, target: _SimulationTarget
) -> bool:
    assignment = draft.assignment
    if assignment is None:
        return draft.operation == "replace_policy"
    if assignment.scope_type == "org":
        return True
    if assignment.scope_type == "team":
        return assignment.team_id == target.team_id
    if assignment.scope_type == "project":
        return assignment.project_id == target.project_id
    if assignment.scope_type == "virtual_key":
        return assignment.virtual_key_id == target.virtual_key_id
    return False


async def _route_context_from_access_attempt(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    attempt: PolicySimulationRouteAttempt,
    fallback_disabled_reason: str | None,
    db: AsyncSession,
) -> _SimulationRouteContext:
    if (
        attempt.provider_id is None
        or attempt.credential_pool_id is None
        or attempt.provider_model_offering_id is None
        or attempt.provider_model is None
    ):
        raise VirtualKeyNotFoundError
    context = _SimulationRouteContext(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        access_policy_id=attempt.access_policy_id,
        access_policy_revision_id=attempt.access_policy_revision_id,
        access_policy_assignment_id=attempt.access_policy_assignment_id,
        access_policy_route_id=None,
        public_model_id=attempt.public_model_id,
        route_candidate_id=attempt.route_candidate_id,
        primary_route_candidate_id=attempt.route_candidate_id,
        public_model_name=attempt.public_model_name,
        routing_mode=attempt.routing_mode,
        model_offering_id=attempt.provider_model_offering_id,
        limit_policy_ids=[],
        limit_policies=[],
        virtual_key_id=target.virtual_key_id,
        provider_id=attempt.provider_id,
        pool_id=attempt.credential_pool_id,
        provider_key_id=None,
        requested_model=payload.requested_model,
        provider_model=attempt.provider_model,
        input_price_per_million_tokens=attempt.input_price_per_million_tokens,
        output_price_per_million_tokens=attempt.output_price_per_million_tokens,
        fallback_disabled_reason=fallback_disabled_reason,
        draft_ref=attempt.draft_ref,
    )
    limit_policies = await _saved_limit_policies_for_route_context(
        target=target,
        resolved=context,
        db=db,
    )
    return context.model_copy(
        update={
            "limit_policies": limit_policies,
            "limit_policy_ids": list(
                {
                    limit.limit_policy_id
                    for limit in limit_policies
                    if limit.limit_policy_id is not None
                }
            ),
        }
    )


async def _resolved_with_limit_drafts(
    *,
    payload: PolicySimulationRequest,
    resolved: _SimulationRouteContext,
    warnings: list[PolicySimulationWarning],
    target: _SimulationTarget,
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> _SimulationRouteContext:
    replaced_limit_policy_ids = {
        replacement_index.limit[draft.existing_policy_id].concrete_id
        for draft in payload.drafts
        if draft.kind == "limit"
        and draft.operation == "replace_policy"
        and draft.existing_policy_id is not None
        and draft.existing_policy_id in replacement_index.limit
    }
    active_concrete_replaced_limit_policy_ids = {
        limit.limit_policy_id
        for limit in resolved.limit_policies
        if limit.limit_policy_id in replaced_limit_policy_ids
    }
    active_replacement_assignment_ids: dict[UUID | None, list[UUID | None]] = {}
    for limit in resolved.limit_policies:
        if limit.limit_policy_id not in active_concrete_replaced_limit_policy_ids:
            continue
        assignment_ids = active_replacement_assignment_ids.setdefault(limit.limit_policy_id, [])
        if limit.limit_policy_assignment_id not in assignment_ids:
            assignment_ids.append(limit.limit_policy_assignment_id)
    saved_limits = [
        limit
        for limit in resolved.limit_policies
        if limit.limit_policy_id not in replaced_limit_policy_ids
    ]
    saved_limit_ids = [
        limit_id
        for limit_id in resolved.limit_policy_ids
        if limit_id not in replaced_limit_policy_ids
    ]
    draft_limits, assignment_counter_refs = await _resolved_limit_policy_drafts(
        payload.drafts,
        target=target,
        resolved=resolved,
        active_replaced_limit_policy_ids=active_concrete_replaced_limit_policy_ids,
        active_replacement_assignment_ids=active_replacement_assignment_ids,
        replacement_index=replacement_index,
        db=db,
    )
    if not draft_limits and len(saved_limits) == len(resolved.limit_policies):
        return resolved
    warning_refs = {warning.draft_ref for warning in warnings}
    for draft_limit in draft_limits:
        if (
            draft_limit.limit_policy_id is not None
            and draft_limit.limit_policy_rule_id is not None
            and draft_limit.limit_policy_assignment_id is not None
        ):
            continue
        if draft_limit.draft_ref not in warning_refs:
            warning_code = (
                "draft_limit_assignment_counter_starts_at_zero"
                if draft_limit.draft_ref in assignment_counter_refs
                else "draft_limit_counter_starts_at_zero"
            )
            warnings.append(
                PolicySimulationWarning(
                    code=warning_code,
                    message="Draft limit counters start at zero until the policy is saved.",
                    draft_ref=draft_limit.draft_ref,
                )
            )
            warning_refs.add(draft_limit.draft_ref)
    return resolved.model_copy(
        update={
            "limit_policies": [*saved_limits, *draft_limits],
            "limit_policy_ids": saved_limit_ids,
        }
    )


async def _saved_limit_policies_for_route_context(
    *,
    target: _SimulationTarget,
    resolved: _SimulationRouteContext,
    db: AsyncSession,
) -> list[ResolvedLimitPolicy]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        policy_type="limit",
        db=db,
    )
    limits: list[ResolvedLimitPolicy] = []
    for assignment in assignments:
        if assignment.limit_policy_id is None:
            continue
        policy = await policies_repository.get_limit_policy(
            policy_id=assignment.limit_policy_id,
            org_id=target.org_id,
            db=db,
        )
        if policy is None or policy.policy_id is None or not policy.is_active:
            continue
        active_revision = await policies_repository.get_active_policy_revision(
            org_id=target.org_id,
            policy_id=policy.policy_id,
            db=db,
        )
        if active_revision is None:
            continue
        rules = await policies_repository.list_limit_policy_revision_rules(
            org_id=target.org_id,
            limit_policy_id=policy.id,
            policy_revision_id=active_revision.id,
            db=db,
        )
        limits.extend(
            _resolved_limit_policy_from_saved(rule=rule, policy=policy, assignment_id=assignment.id)
            for rule in rules
            if rule.is_active and _limit_rule_filters_match(rule=rule, resolved=resolved)
        )
    return limits


def _resolved_limit_policy_from_saved(*, rule, policy, assignment_id: UUID) -> ResolvedLimitPolicy:
    return ResolvedLimitPolicy(
        limit_policy_assignment_id=assignment_id,
        limit_policy_id=policy.id,
        limit_policy_revision_id=rule.policy_revision_id,
        limit_policy_name=policy.name,
        limit_policy_rule_id=rule.id,
        name=rule.name,
        limit_type=rule.limit_type,
        limit_value=rule.limit_value,
        interval_unit=rule.interval_unit,
        interval_count=rule.interval_count,
    )


async def _resolved_limit_policy_drafts(
    drafts: list[PolicySimulationDraft],
    *,
    target: _SimulationTarget,
    resolved: _SimulationRouteContext,
    active_replaced_limit_policy_ids: set[UUID | None],
    active_replacement_assignment_ids: dict[UUID | None, list[UUID | None]],
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> tuple[list[ResolvedLimitPolicy], set[str]]:
    draft_limits: list[ResolvedLimitPolicy] = []
    assignment_counter_refs: set[str] = set()
    for draft_index, draft in enumerate(drafts):
        if draft.kind != "limit" or draft.limit_policy is None:
            continue
        if not draft.limit_policy.is_active:
            continue
        if not _limit_draft_applies(
            draft=draft,
            target=target,
            active_replaced_limit_policy_ids=active_replaced_limit_policy_ids,
            replacement_index=replacement_index,
        ):
            continue
        replacement = (
            replacement_index.limit.get(draft.existing_policy_id)
            if draft.existing_policy_id is not None
            else None
        )
        saved_rules = await _saved_limit_rules_for_replacement(
            org_id=target.org_id,
            replacement=replacement,
            db=db,
        )
        for index, rule in enumerate(draft.limit_policy.rules):
            if not rule.is_active:
                continue
            if not _limit_rule_filters_match(rule=rule, resolved=resolved):
                continue
            draft_ref = f"draft[{draft_index}]:limit_policy.rules[{index}]"
            saved_rule = saved_rules[index] if index < len(saved_rules) else None
            preserve_saved_ids = draft.operation == "replace_policy" and replacement is not None
            if preserve_saved_ids and draft.assignment is not None:
                assignment_counter_refs.add(draft_ref)
            assignment_ids = (
                active_replacement_assignment_ids.get(replacement.concrete_id, [])
                if preserve_saved_ids and draft.assignment is None
                else [None]
            )
            for assignment_id in assignment_ids:
                draft_limits.append(
                    ResolvedLimitPolicy(
                        limit_policy_assignment_id=assignment_id,
                        limit_policy_id=replacement.concrete_id if preserve_saved_ids else None,
                        limit_policy_revision_id=(
                            saved_rule.policy_revision_id
                            if preserve_saved_ids and saved_rule is not None
                            else None
                        ),
                        limit_policy_name=draft.limit_policy.name,
                        limit_policy_rule_id=(
                            saved_rule.id
                            if preserve_saved_ids and saved_rule is not None
                            else None
                        ),
                        name=rule.name,
                        limit_type=rule.limit_type,
                        limit_value=rule.limit_value,
                        interval_unit=rule.interval_unit,
                        interval_count=rule.interval_count,
                        matchers=[matcher.model_dump() for matcher in rule.matchers],
                        partitions=[partition.model_dump() for partition in rule.partitions],
                        draft_ref=draft_ref,
                    )
                )
    return draft_limits, assignment_counter_refs


async def _saved_limit_rules_for_replacement(
    *, org_id: UUID, replacement: _ReplacementPolicy | None, db: AsyncSession
):
    if replacement is None or replacement.shared_policy_id is None:
        return []
    active_revision = await policies_repository.get_active_policy_revision(
        org_id=org_id,
        policy_id=replacement.shared_policy_id,
        db=db,
    )
    if active_revision is None:
        return []
    return await policies_repository.list_limit_policy_revision_rules(
        org_id=org_id,
        limit_policy_id=replacement.concrete_id,
        policy_revision_id=active_revision.id,
        db=db,
    )


def _limit_draft_applies(
    *,
    draft: PolicySimulationDraft,
    target: _SimulationTarget,
    active_replaced_limit_policy_ids: set[UUID | None],
    replacement_index: _ReplacementIndex,
) -> bool:
    if draft.operation == "replace_policy":
        replacement = (
            replacement_index.limit.get(draft.existing_policy_id)
            if draft.existing_policy_id is not None
            else None
        )
        if replacement is None:
            return False
        if draft.assignment is None:
            return replacement.concrete_id in active_replaced_limit_policy_ids
    return _draft_assignment_matches_target(draft=draft, target=target)


def _limit_rule_filters_match(*, rule, resolved: _SimulationRouteContext) -> bool:
    provider_id = getattr(rule, "provider_id", None)
    credential_pool_id = getattr(rule, "credential_pool_id", None)
    model_offering_id = getattr(rule, "model_offering_id", None)
    access_policy_id = getattr(rule, "access_policy_id", None)
    if provider_id is not None and provider_id != resolved.provider_id:
        return False
    if credential_pool_id is not None and credential_pool_id != resolved.pool_id:
        return False
    if model_offering_id is not None and model_offering_id != resolved.model_offering_id:
        return False
    if access_policy_id is not None and access_policy_id != resolved.access_policy_id:
        return False
    return True


async def _effective_guardrail_rules(
    *,
    context: GuardrailEvaluationContext,
    payload: PolicySimulationRequest,
    target: _SimulationTarget,
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> list[RuntimeGuardrailRuleInput]:
    saved_rules = await guardrails_facade.runtime_rules_for_context_readonly(
        context=context,
        db=db,
    )
    replaced_policy_ids = {
        replacement_index.guardrail[draft.existing_policy_id].concrete_id
        for draft in payload.drafts
        if draft.kind == "guardrail"
        and draft.operation == "replace_policy"
        and draft.existing_policy_id is not None
        and draft.existing_policy_id in replacement_index.guardrail
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
    target: _SimulationTarget,
    active_replaced_policy_ids: set[UUID | None],
    replacement_index: _ReplacementIndex,
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
    target: _SimulationTarget,
    active_replaced_policy_ids: set[UUID | None],
    replacement_index: _ReplacementIndex,
) -> bool:
    if draft.operation == "replace_policy":
        replacement = (
            replacement_index.guardrail.get(draft.existing_policy_id)
            if draft.existing_policy_id is not None
            else None
        )
        if replacement is None:
            return False
        if draft.assignment is None:
            return replacement.concrete_id in active_replaced_policy_ids
    return _draft_assignment_matches_target(draft=draft, target=target)


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
    attempt: _SimulationRouteContext,
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


def _estimated_cost_cents(
    *,
    payload: PolicySimulationRequest,
    resolved: _SimulationRouteContext,
) -> int | None:
    return default_cost_calculator_registry.calculate_cents(
        context=_costing_context(resolved),
        usage=_estimated_usage(payload),
    )


def _estimated_cost_micro_cents(
    *,
    payload: PolicySimulationRequest,
    resolved: _SimulationRouteContext,
) -> int | None:
    return default_cost_calculator_registry.calculate_micro_cents(
        context=_costing_context(resolved),
        usage=_estimated_usage(payload),
    )


def _estimated_usage(payload: PolicySimulationRequest) -> UsageAccounting:
    return UsageAccounting(
        prompt_tokens=payload.estimated_input_tokens,
        completion_tokens=payload.requested_output_tokens or 0,
        total_tokens=payload.estimated_input_tokens + (payload.requested_output_tokens or 0),
        usage_source="simulation",
    )


def _costing_context(resolved: _SimulationRouteContext) -> CostingContext:
    return CostingContext(
        provider_id=str(resolved.provider_id),
        provider_model=resolved.provider_model,
        input_price_per_million_tokens=resolved.input_price_per_million_tokens,
        output_price_per_million_tokens=resolved.output_price_per_million_tokens,
    )


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
