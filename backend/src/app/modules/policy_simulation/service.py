from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import AuthorizationTarget
from app.modules.keys.errors import VirtualKeyNotFoundError
from app.modules.keys.schemas import ResolvedLimitPolicy
from app.modules.policies.errors import PolicyPermissionError, PolicyValidationError
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.runtime_limits import (
    RuntimeLimitEvaluationInput,
    evaluate_runtime_limits_readonly,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_simulation import adapters
from app.modules.policy_simulation.draft_validation import validate_policy_simulation_drafts
from app.modules.policy_simulation.errors import (
    PolicySimulationPermissionError,
    PolicySimulationValidationError,
)
from app.modules.policy_simulation.schemas import (
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
from app.modules.workspace import facade as workspace_facade


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


@dataclass(frozen=True)
class _AccessRouteResources:
    provider: Any | None
    pool: Any | None
    model: Any | None


@dataclass
class _AccessAttemptState:
    matched_public_model_name: str | None = None
    selected_public_model: _AccessPublicModelRef | None = None
    selected_attempt: PolicySimulationRouteAttempt | None = None
    attempted_count: int = 0
    fallback_disabled_reason: str | None = None


async def simulate_active_policies(
    *,
    org_id,
    payload: PolicySimulationRequest,
    actor: AuthenticatedUser | None,
    db: AsyncSession,
) -> PolicySimulationResponse:
    try:
        validate_policy_simulation_drafts(payload.drafts)
    except PolicySimulationValidationError as exc:
        raise PolicyValidationError from exc
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
        guardrail_outcome = await adapters.guardrail.simulate_guardrails_for_attempts(
            payload=payload,
            attempts=resolved_attempts,
            target=target,
            replacement_index=replacement_index.guardrail,
            initial_final_decision=final_decision,
            initial_denied_stage=denied_stage,
            initial_denied_reason=denied_reason,
            db=db,
        )
        guardrail_results.extend(guardrail_outcome.results)
        decisions.extend(guardrail_outcome.decisions)
        warnings.extend(guardrail_outcome.warnings)
        final_decision = guardrail_outcome.final_decision
        denied_stage = guardrail_outcome.denied_stage
        denied_reason = guardrail_outcome.denied_reason

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
    target = await workspace_facade.get_virtual_key_target(
        scope=Scope(org_id=org_id),
        virtual_key_id=virtual_key_id,
        db=db,
    )
    if target is None:
        raise VirtualKeyNotFoundError
    return _SimulationTarget(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        virtual_key_name=target.virtual_key_name,
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
                db=db,
            ):
                raise PolicyPermissionError
            limit[draft.existing_policy_id] = _ReplacementPolicy(
                concrete_id=policy.id,
                shared_policy_id=policy.policy_id,
            )
            continue
        try:
            replacement = await adapters.guardrail.validate_guardrail_replacement_policy(
                org_id=org_id,
                policy_id=draft.existing_policy_id,
                actor_is_scoped=_is_scoped_actor(actor),
                actor_can_manage_all=(
                    actor is None
                    or authorization_facade.has_permission(actor, Permissions.POLICIES_VIEW)
                ),
                assignment_visible=lambda assignment: _assignment_visible_to_actor(
                    actor=actor,
                    target=target,
                    assignment=assignment,
                    db=db,
                ),
                db=db,
            )
        except PolicySimulationPermissionError as exc:
            raise PolicyPermissionError from exc
        except PolicySimulationValidationError as exc:
            raise PolicyValidationError from exc
        guardrail[draft.existing_policy_id] = _ReplacementPolicy(
            concrete_id=replacement.concrete_id,
            shared_policy_id=replacement.shared_policy_id,
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
    policy_view = await _can_access_simulation_target(
        actor=actor,
        target=target,
        permission=Permissions.POLICIES_VIEW,
        db=db,
    )
    if not policy_view:
        raise PolicyPermissionError
    guardrail_requested = payload.include_guardrails or any(
        draft.kind == "guardrail" for draft in payload.drafts
    )
    guardrail_view = await _can_access_simulation_target(
        actor=actor,
        target=target,
        permission=Permissions.GUARDRAILS_VIEW,
        db=db,
    )
    if guardrail_requested and not guardrail_view:
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

def _is_scoped_actor(actor: AuthenticatedUser | None) -> bool:
    if actor is None:
        return False
    return not authorization_facade.has_permission(actor, Permissions.POLICIES_VIEW)


async def _can_replace_policy(
    *,
    actor: AuthenticatedUser | None,
    target: _SimulationTarget,
    policy,
    db: AsyncSession,
) -> bool:
    if actor is None:
        return True
    if authorization_facade.has_permission(actor, Permissions.POLICIES_VIEW):
        return True
    if await _policy_owned_in_actor_scope(actor=actor, policy=policy, target=target, db=db):
        return True
    assignments = await policy_kernel_repository.list_policy_assignments_for_policy(
        org_id=target.org_id,
        policy_id=policy.policy_id,
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


async def _policy_owned_in_actor_scope(
    *, actor: AuthenticatedUser, policy, target: _SimulationTarget, db: AsyncSession
) -> bool:
    if policy.owning_scope_type in {"team", "project", "virtual_key"}:
        decision = await authorization_facade.can(
            actor=actor,
            permission=Permissions.POLICIES_VIEW,
            target=AuthorizationTarget.workspace_scope(
                scope_type=policy.owning_scope_type,
                team_id=policy.owning_team_id,
                project_id=policy.owning_project_id,
                virtual_key_id=policy.owning_virtual_key_id,
            ),
            scope=Scope(org_id=target.org_id),
            db=db,
        )
        return decision.allowed
    return False


async def _assignment_visible_to_actor(
    *, actor: AuthenticatedUser, target: _SimulationTarget, assignment, db: AsyncSession
) -> bool:
    decision = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_VIEW,
        target=AuthorizationTarget.workspace_scope(
            scope_type=assignment.scope_type,
            team_id=assignment.team_id,
            project_id=assignment.project_id,
            virtual_key_id=assignment.virtual_key_id,
        ),
        scope=Scope(org_id=target.org_id),
        db=db,
    )
    return decision.allowed


async def _can_simulate_draft_assignment(
    *,
    actor: AuthenticatedUser,
    target: _SimulationTarget,
    assignment,
    db: AsyncSession,
) -> bool:
    if authorization_facade.has_permission(actor, Permissions.POLICIES_VIEW):
        return True
    decision = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=AuthorizationTarget.assignment_scope(
            scope_type=assignment.scope_type,
            team_id=assignment.team_id,
            project_id=assignment.project_id,
            virtual_key_id=assignment.virtual_key_id,
        ),
        scope=Scope(org_id=target.org_id),
        db=db,
    )
    return decision.allowed


async def _can_access_simulation_target(
    *,
    actor: AuthenticatedUser,
    target: _SimulationTarget,
    permission: str,
    db: AsyncSession,
) -> bool:
    decision = await authorization_facade.can(
        actor=actor,
        permission=permission,
        target=AuthorizationTarget.workspace_scope(
            scope_type="virtual_key",
            virtual_key_id=target.virtual_key_id,
        ),
        scope=Scope(org_id=target.org_id),
        db=db,
    )
    return decision.allowed


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
    _sort_access_candidates(candidates)
    route_attempts: list[PolicySimulationRouteAttempt] = []
    decisions: list[PolicySimulationDecision] = []
    resolved_attempts: list[tuple[UUID | None, _SimulationRouteContext, bool]] = []
    state = _AccessAttemptState()
    for candidate_index, candidate in enumerate(candidates):
        resources = await _route_resources_for_candidate(
            candidate=candidate,
            target=target,
            db=db,
        )
        would_attempt, skipped_reason, skipped_message = _access_attempt_decision(
            payload=payload,
            candidate=candidate,
            resources=resources,
            state=state,
        )
        attempt = _simulation_route_attempt_from_candidate(
            candidate_index=candidate_index,
            candidate=candidate,
            resources=resources,
            would_attempt=would_attempt,
            skipped_reason=skipped_reason,
            skipped_message=skipped_message,
            state=state,
        )
        route_attempts.append(attempt)
        decisions.append(_routing_decision_from_attempt(attempt))
        if would_attempt:
            context = await _route_context_from_access_attempt(
                target=target,
                payload=payload,
                attempt=attempt,
                fallback_disabled_reason=state.fallback_disabled_reason,
                db=db,
            )
            resolved_attempts.append((attempt.route_candidate_id, context, attempt.selected))
        if attempt.selected:
            state.selected_attempt = attempt
    return _access_resolution_from_attempts(
        payload=payload,
        route_attempts=route_attempts,
        decisions=decisions,
        resolved_attempts=resolved_attempts,
        state=state,
    )


def _sort_access_candidates(candidates: list[_AccessCandidateRef]) -> None:
    candidates.sort(
        key=lambda item: (
            item.priority,
            -item.weight,
            item.created_at is None,
            _sort_datetime(item.created_at),
        )
    )


async def _route_resources_for_candidate(
    *,
    candidate: _AccessCandidateRef,
    target: _SimulationTarget,
    db: AsyncSession,
) -> _AccessRouteResources:
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
    return _AccessRouteResources(provider=provider, pool=pool, model=model)


def _access_attempt_decision(
    *,
    payload: PolicySimulationRequest,
    candidate: _AccessCandidateRef,
    resources: _AccessRouteResources,
    state: _AccessAttemptState,
) -> tuple[bool, str | None, str | None]:
    skipped_reason, skipped_message = _access_candidate_skip_reason(
        payload=payload,
        candidate=candidate,
        provider=resources.provider,
        pool=resources.pool,
        model=resources.model,
        matched_public_model_name=state.matched_public_model_name,
    )
    would_attempt = skipped_reason is None
    if would_attempt and state.matched_public_model_name is None:
        state.matched_public_model_name = candidate.public_model.public_model_name
        state.selected_public_model = candidate.public_model
    if (
        would_attempt
        and state.matched_public_model_name != candidate.public_model.public_model_name
    ):
        return False, "routing_mode_disables_fallback", _routing_disabled_message()
    if would_attempt and state.selected_public_model is not None:
        would_attempt = _update_access_attempt_state(
            payload=payload,
            selected_public_model=state.selected_public_model,
            state=state,
        )
        if not would_attempt and skipped_reason is None:
            skipped_reason = "routing_mode_disables_fallback"
            skipped_message = _routing_disabled_message()
    return would_attempt, skipped_reason, skipped_message


def _update_access_attempt_state(
    *,
    payload: PolicySimulationRequest,
    selected_public_model: _AccessPublicModelRef,
    state: _AccessAttemptState,
) -> bool:
    if selected_public_model.routing_mode == "single_route" and state.attempted_count > 0:
        return False
    if payload.streaming and state.attempted_count > 0:
        state.fallback_disabled_reason = "streaming_fallback_phase_2"
        return False
    if payload.provider_id is not None and state.attempted_count > 0:
        state.fallback_disabled_reason = "provider_pinned"
        return False
    return not (
        selected_public_model.max_route_attempts is not None
        and state.attempted_count >= selected_public_model.max_route_attempts
    )


def _routing_disabled_message() -> str:
    return "The selected routing mode did not attempt this route."


def _simulation_route_attempt_from_candidate(
    *,
    candidate_index: int,
    candidate: _AccessCandidateRef,
    resources: _AccessRouteResources,
    would_attempt: bool,
    skipped_reason: str | None,
    skipped_message: str | None,
    state: _AccessAttemptState,
) -> PolicySimulationRouteAttempt:
    attempt_index = state.attempted_count if would_attempt else None
    selected = would_attempt and state.selected_attempt is None
    if would_attempt:
        state.attempted_count += 1
    model = resources.model
    return PolicySimulationRouteAttempt(
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
        provider_name=resources.provider.name if resources.provider else None,
        credential_pool_id=candidate.credential_pool_id,
        credential_pool_name=resources.pool.name if resources.pool else None,
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


def _access_resolution_from_attempts(
    *,
    payload: PolicySimulationRequest,
    route_attempts: list[PolicySimulationRouteAttempt],
    decisions: list[PolicySimulationDecision],
    resolved_attempts: list[tuple[UUID | None, _SimulationRouteContext, bool]],
    state: _AccessAttemptState,
) -> _AccessResolution:
    if state.selected_attempt is None:
        return _AccessResolution(
            route_attempts=route_attempts,
            decisions=decisions,
            resolved_attempts=[],
            access_denied_reason="no_matching_route",
            public_model_name=None,
            routing_mode=None,
            fallback_on=[],
            provider_pinned=payload.provider_id is not None,
            fallback_disabled_reason=state.fallback_disabled_reason,
        )
    attempts_to_evaluate = (
        resolved_attempts if payload.evaluate_all_route_candidates else resolved_attempts[:1]
    )
    return _AccessResolution(
        route_attempts=route_attempts,
        decisions=decisions,
        resolved_attempts=attempts_to_evaluate,
        access_denied_reason=None,
        public_model_name=state.selected_attempt.public_model_name,
        routing_mode=state.selected_attempt.routing_mode,
        fallback_on=state.selected_public_model.fallback_on if state.selected_public_model else [],
        provider_pinned=payload.provider_id is not None,
        fallback_disabled_reason=state.fallback_disabled_reason,
    )


async def _effective_access_candidates_with_drafts(
    *,
    target: _SimulationTarget,
    payload: PolicySimulationRequest,
    replacement_index: _ReplacementIndex,
    db: AsyncSession,
) -> list[_AccessCandidateRef]:
    saved_assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
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
                assignment.policy_id == replacement.shared_policy_id
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
    policy = await policy_kernel_repository.get_policy(
        policy_id=assignment.policy_id,
        org_id=org_id,
        db=db,
    )
    if policy is None or policy.kind != "access" or not policy.is_active:
        return []
    revision = await policy_kernel_repository.get_active_policy_revision(
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
    candidates: list[_AccessCandidateRef] = []
    for public_model in public_models:
        if not public_model.is_active:
            continue
        public_model_ref = _AccessPublicModelRef(
            public_model_id=public_model.id,
            access_policy_id=assignment.policy_id,
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
        access_policy_id=None,
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
    assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        policy_type="limit",
        db=db,
    )
    limits: list[ResolvedLimitPolicy] = []
    for assignment in assignments:
        policy = await policies_repository.get_limit_policy_by_shared_policy(
            shared_policy_id=assignment.policy_id,
            org_id=target.org_id,
            db=db,
        )
        if policy is None or not policy.is_active:
            continue
        active_revision = await policy_kernel_repository.get_active_policy_revision(
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
    active_revision = await policy_kernel_repository.get_active_policy_revision(
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


