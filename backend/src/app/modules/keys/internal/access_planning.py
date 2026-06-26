from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import hash_token
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository, state
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.runtime_routes import (
    ResolvedAccessPlanExplanation,
    RouteCandidateExplanation,
)
from app.modules.keys.schemas import (
    AccessibleModel,
    AccessibleModelCandidate,
    EffectiveAccessSummary,
    EffectiveLimitReference,
    EffectivePolicyReference,
    EffectiveRouteSummary,
    OwnershipChainState,
    ResolveAccessPlanForSubjectRequest,
    ResolveAccessPlanForVirtualKeyRequest,
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedAccessPlan,
    ResolvedKeySubject,
    ResolvedLimitPolicy,
    ResolvedRouteAttempt,
    ResolveKeySubjectRequest,
)
from app.modules.policies import read_models as policy_read_models
from app.modules.providers import read_models as provider_read_models
from app.modules.providers.schemas import (
    ProviderRouteResource,
    ProviderRouteResourceKey,
)
from app.modules.teams import facade as teams_facade
from app.modules.teams.errors import TeamInactiveError, TeamNotFoundError
from app.modules.workspace.errors import OrganizationInactiveError, ProjectNotFoundError
from app.modules.workspace.internal import repository as workspace_repository
from app.modules.workspace.internal.models import Project

type ResolvedKeyProject = tuple[VirtualKey, Project]
type EffectiveAccessRouteCandidate = policy_read_models.AccessRuntimeRouteCandidate
type LimitRuleMatch = policy_read_models.LimitRuntimeRule
type ResolvedPolicyRoute = tuple[
    policy_read_models.AccessRuntimeRouteCandidate,
    ProviderRouteResource,
]


async def batch_inventory_routing_readiness(
    *,
    rows: list[tuple[VirtualKey, Project]],
    db: AsyncSession,
) -> dict[UUID, bool]:
    if not rows:
        return {}
    org_id = rows[0][0].org_id
    candidates = await policy_read_models.list_access_inventory_route_candidates_for_targets(
        org_id=org_id,
        team_ids={project.team_id for _key, project in rows},
        project_ids={project.id for _key, project in rows},
        virtual_key_ids={key.id for key, _project in rows},
        db=db,
    )
    route_resources = await provider_read_models.get_route_resources(
        org_id=org_id,
        resources={
            ProviderRouteResourceKey(
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_offering_id=candidate.model_offering_id,
            )
            for candidate in candidates
        },
        include_provider=False,
        include_pricing=False,
        db=db,
    )
    candidates_by_policy: dict[UUID, set[tuple[UUID, UUID, UUID]]] = {}
    for candidate in candidates:
        signatures = candidates_by_policy.setdefault(candidate.shared_policy_id, set())
        resource = route_resources.get(
            ProviderRouteResourceKey(
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_offering_id=candidate.model_offering_id,
            )
        )
        if resource is not None and _route_resource_is_inventory_ready(resource):
            signatures.add(
                (candidate.provider_id, candidate.credential_pool_id, candidate.model_offering_id)
            )

    assignments = list({candidate.assignment_id: candidate for candidate in candidates}.values())
    scope_order = ("org", "team", "project", "virtual_key")
    readiness: dict[UUID, bool] = {}
    for key, project in rows:
        effective: set[tuple[UUID, UUID, UUID]] | None = None
        for scope_type in scope_order:
            scoped_assignments = [
                assignment
                for assignment in assignments
                if assignment.source_scope == scope_type
                and (
                    scope_type == "org"
                    or (scope_type == "team" and assignment.assignment_team_id == project.team_id)
                    or (
                        scope_type == "project"
                        and assignment.assignment_project_id == project.id
                    )
                    or (
                        scope_type == "virtual_key"
                        and assignment.assignment_virtual_key_id == key.id
                    )
                )
            ]
            candidates = set().union(
                *(
                    candidates_by_policy.get(assignment.shared_policy_id, set())
                    for assignment in scoped_assignments
                )
            )
            if not candidates:
                continue
            effective = candidates if effective is None else candidates & effective
        readiness[key.id] = bool(effective)
    return readiness


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    plan = await resolve_access_plan(payload=payload, db=db)
    primary = plan.attempts[0]
    return ResolvedAccess(
        org_id=primary.org_id,
        team_id=primary.team_id,
        project_id=primary.project_id,
        access_policy_id=primary.access_policy_id,
        access_policy_revision_id=primary.access_policy_revision_id,
        access_policy_assignment_id=primary.access_policy_assignment_id,
        access_policy_route_id=primary.access_policy_route_id,
        public_model_id=primary.public_model_id,
        route_candidate_id=primary.route_candidate_id,
        primary_route_candidate_id=primary.primary_route_candidate_id,
        public_model_name=primary.public_model_name,
        routing_mode=primary.routing_mode,
        model_offering_id=primary.model_offering_id,
        limit_policy_ids=primary.limit_policy_ids,
        limit_policies=primary.limit_policies,
        virtual_key_id=primary.virtual_key_id,
        provider_id=primary.provider_id,
        pool_id=primary.pool_id,
        provider_key_id=primary.provider_key_id,
        requested_model=primary.requested_model,
        provider_model=primary.provider_model,
        input_price_per_million_tokens=primary.input_price_per_million_tokens,
        output_price_per_million_tokens=primary.output_price_per_million_tokens,
        fallback_disabled_reason=plan.fallback_disabled_reason,
    )


async def resolve_key_subject(
    *,
    payload: ResolveKeySubjectRequest,
    db: AsyncSession,
) -> ResolvedKeySubject:
    virtual_key, project = await _resolve_key_project(
        raw_key=payload.raw_key,
        db=db,
    )
    team_labels = await teams_facade.get_team_labels(
        team_ids={project.team_id},
        scope=Scope(org_id=virtual_key.org_id),
        db=db,
    )
    return ResolvedKeySubject(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        virtual_key_name=virtual_key.name,
        project_name=project.name,
        team_name=team_labels.get(project.team_id),
    )


async def resolve_access_plan(
    *,
    payload: ResolveAccessRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    subject = await resolve_key_subject(
        payload=ResolveKeySubjectRequest(raw_key=payload.raw_key),
        db=db,
    )
    return await resolve_access_plan_for_subject(
        payload=ResolveAccessPlanForSubjectRequest(
            subject=subject,
            requested_model=payload.requested_model,
            provider_id=payload.provider_id,
            streaming=payload.streaming,
            gateway_endpoint=payload.gateway_endpoint,
        ),
        db=db,
    )


async def resolve_access_plan_for_subject(
    *,
    payload: ResolveAccessPlanForSubjectRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    subject = payload.subject
    virtual_key = await repository.get_virtual_key(
        org_id=subject.org_id,
        project_id=subject.project_id,
        key_id=subject.virtual_key_id,
        db=db,
    )
    project = await workspace_repository.get_project(
        project_id=subject.project_id,
        org_id=subject.org_id,
        db=db,
    )
    if virtual_key is None or project is None or project.team_id != subject.team_id:
        raise InvalidVirtualKeyError
    return await _build_resolved_access_plan(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        streaming=payload.streaming,
        db=db,
    )


async def resolve_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    virtual_key, project = await _resolve_key_project_readonly(
        org_id=org_id,
        virtual_key_id=payload.virtual_key_id,
        db=db,
    )
    return await _build_resolved_access_plan(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        streaming=payload.streaming,
        db=db,
    )


async def explain_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlanExplanation:
    virtual_key, project = await _resolve_key_project_readonly(
        org_id=org_id,
        virtual_key_id=payload.virtual_key_id,
        db=db,
    )
    plan: ResolvedAccessPlan | None = None
    access_denied_reason: str | None = None
    try:
        plan = await _build_resolved_access_plan(
            virtual_key=virtual_key,
            project=project,
            requested_model=payload.requested_model,
            provider_id=payload.provider_id,
            gateway_endpoint=payload.gateway_endpoint,
            streaming=payload.streaming,
            db=db,
        )
    except AccessDeniedError:
        access_denied_reason = "no_matching_route"
    candidates = await _explain_route_candidates(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        plan=plan,
        db=db,
    )
    return ResolvedAccessPlanExplanation(
        plan=plan,
        candidates=candidates,
        access_denied_reason=access_denied_reason,
    )


async def _build_resolved_access_plan(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    streaming: bool,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    matched = await _match_policy_route(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        requested_model=requested_model,
        provider_id=provider_id,
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    if not matched:
        raise AccessDeniedError
    primary_candidate = matched[0][0]
    attempts: list[ResolvedRouteAttempt] = []
    attempt_limit_rules: list[list[LimitRuleMatch]] = []
    for index, (attempt_candidate, attempt_resource) in enumerate(matched):
        limit_rules = await _matching_limit_policies(
            org_id=virtual_key.org_id,
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            route=attempt_candidate,
            db=db,
        )
        attempt_limit_rules.append(limit_rules)
        attempts.append(
            _to_resolved_route_attempt(
                virtual_key=virtual_key,
                project=project,
                requested_model=requested_model,
                candidate=attempt_candidate,
                resource=attempt_resource,
                attempt_index=index,
                primary_route_candidate_id=primary_candidate.route_candidate_id,
                limit_rules=limit_rules,
            )
        )
    fallback_disabled_reason = None
    if provider_id is not None and len(attempts) == 1:
        fallback_disabled_reason = "provider_pinned"
    if streaming and len(attempts) > 1:
        attempts = attempts[:1]
        fallback_disabled_reason = "streaming_fallback_phase_2"
    plan_limit_rules = attempt_limit_rules[0] if attempt_limit_rules else []
    return ResolvedAccessPlan(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        requested_model=requested_model,
        public_model_name=primary_candidate.public_model_name,
        routing_mode=primary_candidate.routing_mode,
        fallback_on=primary_candidate.fallback_on,
        max_route_attempts=primary_candidate.max_route_attempts,
        provider_pinned=provider_id is not None,
        fallback_disabled_reason=fallback_disabled_reason,
        limit_policy_ids=list({rule.limit_policy_id for rule in plan_limit_rules}),
        limit_policies=[
            _to_resolved_limit_policy(rule)
            for rule in plan_limit_rules
        ],
        attempts=attempts,
    )


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    virtual_key, project = await _resolve_key_project(
        raw_key=raw_key,
        db=db,
    )
    models: list[AccessibleModel] = []
    by_id: dict[str, AccessibleModel] = {}
    for candidate in await build_effective_access_routes_readonly(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    ):
        routable = await _routable_route_candidate(
            org_id=virtual_key.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        resource = routable
        policy_id = candidate.shared_policy_id
        model_id = _accessible_model_id(candidate=candidate)
        candidate_metadata = _accessible_model_candidate(
            candidate=candidate,
            resource=resource,
        )
        if model_id in by_id:
            by_id[model_id].candidates.append(candidate_metadata)
            continue
        accessible = AccessibleModel(
            id=model_id,
            owned_by=resource.provider_id.hex,
            provider_id=resource.provider_id,
            provider_name=resource.provider_name or "Unknown provider",
            model_offering_id=resource.model_offering_id,
            access_policy_id=policy_id,
            access_policy_name=candidate.policy_name,
            access_policy_route_id=None,
            public_model_id=candidate.public_model_id,
            route_candidate_id=candidate.route_candidate_id,
            public_model_name=candidate.public_model_name,
            routing_mode=candidate.routing_mode,
            pool_id=resource.credential_pool_id,
            pool_name=resource.credential_pool_name or "",
            source_scope=candidate.source_scope,
            candidates=[candidate_metadata],
        )
        by_id[model_id] = accessible
        models.append(accessible)
    return models


async def list_project_accessible_models(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[AccessibleModel]:
    project = await workspace_repository.get_project(
        project_id=project_id, org_id=scope.org_id, db=db
    )
    if project is None or not project.is_active:
        raise ProjectNotFoundError
    models: list[AccessibleModel] = []
    seen: set[tuple[UUID, UUID]] = set()
    for candidate in await build_effective_access_routes_readonly(
        org_id=scope.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=None,
        db=db,
    ):
        routable = await _routable_route_candidate(
            org_id=scope.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        resource = routable
        policy_id = candidate.shared_policy_id
        dedupe_key = (candidate.public_model_id, candidate.route_candidate_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        models.append(
            AccessibleModel(
                id=_accessible_model_id(candidate=candidate),
                owned_by=resource.provider_id.hex,
                provider_id=resource.provider_id,
                provider_name=resource.provider_name or "Unknown provider",
                model_offering_id=resource.model_offering_id,
                access_policy_id=policy_id,
                access_policy_name=candidate.policy_name,
                access_policy_route_id=None,
                public_model_id=candidate.public_model_id,
                route_candidate_id=candidate.route_candidate_id,
                public_model_name=candidate.public_model_name,
                routing_mode=candidate.routing_mode,
                pool_id=resource.credential_pool_id,
                pool_name=resource.credential_pool_name or "",
                source_scope=candidate.source_scope,
            )
        )
    return sorted(models, key=lambda item: (item.id, str(item.provider_id)))


async def get_project_effective_access(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    project = await workspace_repository.get_project(
        project_id=project_id, org_id=scope.org_id, db=db
    )
    if project is None:
        raise ProjectNotFoundError
    return await build_effective_access_summary(project=project, virtual_key=None, db=db)


async def get_virtual_key_effective_access(
    *, project_id: UUID, key_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    project = await workspace_repository.get_project(
        project_id=project_id, org_id=scope.org_id, db=db
    )
    if project is None:
        raise ProjectNotFoundError
    virtual_key = await repository.get_virtual_key(
        org_id=scope.org_id, project_id=project_id, key_id=key_id, db=db
    )
    if virtual_key is None:
        raise VirtualKeyNotFoundError
    return await build_effective_access_summary(project=project, virtual_key=virtual_key, db=db)


async def build_effective_access_summary(
    *, project: Project, virtual_key: VirtualKey | None, db: AsyncSession
) -> EffectiveAccessSummary:
    organization = await workspace_repository.get_organization(org_id=project.org_id, db=db)
    try:
        team = await teams_facade.get_team(
            team_id=project.team_id, scope=Scope(org_id=project.org_id), db=db
        )
        team_active = team.is_active
    except TeamNotFoundError:
        team_active = False
    organization_active = bool(organization and organization.is_active)
    key_active = None
    blocker: tuple[str, str] | None = None
    if virtual_key is not None:
        expired = virtual_key.expires_at is not None and _as_utc(
            virtual_key.expires_at
        ) <= datetime.now(UTC)
        key_active = virtual_key.revoked_at is None and not expired
        if virtual_key.revoked_at is not None:
            blocker = ("key_revoked", "The virtual key has been revoked.")
        elif expired:
            blocker = ("key_expired", "The virtual key has expired.")
    if blocker is None and not organization_active:
        blocker = ("organization_inactive", "The organization is inactive.")
    if blocker is None and not team_active:
        blocker = ("team_archived", "The owning team is archived.")
    if blocker is None and not project.is_active:
        blocker = ("project_archived", "The project is archived.")

    routes = await build_effective_access_routes_readonly(
        org_id=project.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id if virtual_key else None,
        db=db,
    )
    routable_routes: list[EffectiveRouteSummary] = []
    for candidate in routes:
        routable = await _routable_route_candidate(
            org_id=project.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        resource = routable
        routable_routes.append(
            EffectiveRouteSummary(
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_offering_id=resource.model_offering_id,
                public_model_id=candidate.public_model_id,
                route_candidate_id=candidate.route_candidate_id,
                public_model_name=candidate.public_model_name,
                routing_mode=candidate.routing_mode,
                provider_model=resource.provider_model_name or "",
                access_policy_id=candidate.shared_policy_id,
                access_policy_revision_id=candidate.policy_revision_id,
                access_policy_name=candidate.policy_name,
                access_policy_assignment_id=candidate.assignment_id,
                source_scope=candidate.source_scope,
            )
        )

    access_references = await _effective_access_policy_references(
        candidates=list({candidate.assignment_id: candidate for candidate in routes}.values())
    )
    access_reference = access_references[0] if access_references else None
    if blocker is None and access_reference is None:
        blocker = ("no_effective_access_policy", "No effective active access policy applies.")
    elif blocker is None and not routable_routes:
        blocker = (
            "no_routable_provider_model",
            "The effective policy has no currently routable provider and model.",
        )
    limits = await _effective_limit_policy_references(
        org_id=project.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id if virtual_key else None,
        db=db,
    )
    return EffectiveAccessSummary(
        is_usable=blocker is None,
        blocking_code=blocker[0] if blocker else None,
        blocking_reason=blocker[1] if blocker else None,
        ownership=OwnershipChainState(
            organization_active=organization_active,
            team_active=team_active,
            project_active=project.is_active,
            key_active=key_active,
        ),
        access_policy=access_reference,
        access_policies=access_references,
        routes=routable_routes,
        limit_policies=limits,
    )


async def _resolve_key_project(*, raw_key: str, db: AsyncSession) -> ResolvedKeyProject:
    virtual_key = await repository.get_virtual_key_by_hash(key_hash=hash_token(raw_key), db=db)
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    try:
        await _ensure_organization_active(org_id=virtual_key.org_id, db=db)
    except OrganizationInactiveError as exc:
        raise InvalidVirtualKeyError from exc
    project = await workspace_repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError
    try:
        await teams_facade.ensure_team_active(
            team_id=project.team_id,
            scope=Scope(org_id=virtual_key.org_id),
            db=db,
        )
    except (TeamInactiveError, TeamNotFoundError) as exc:
        raise InvalidVirtualKeyError from exc
    virtual_key.last_used_at = datetime.now(UTC)
    await db.flush()
    return virtual_key, project


async def _resolve_key_project_readonly(
    *,
    org_id: UUID,
    virtual_key_id: UUID,
    db: AsyncSession,
) -> ResolvedKeyProject:
    virtual_key = await repository.get_virtual_key_by_id(
        org_id=org_id,
        key_id=virtual_key_id,
        db=db,
    )
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    try:
        await _ensure_organization_active(org_id=virtual_key.org_id, db=db)
    except OrganizationInactiveError as exc:
        raise InvalidVirtualKeyError from exc
    project = await workspace_repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError
    try:
        await teams_facade.ensure_team_active(
            team_id=project.team_id,
            scope=Scope(org_id=virtual_key.org_id),
            db=db,
        )
    except (TeamInactiveError, TeamNotFoundError) as exc:
        raise InvalidVirtualKeyError from exc
    return virtual_key, project


async def _ensure_organization_active(*, org_id: UUID, db: AsyncSession) -> None:
    await state.ensure_organization_active(org_id=org_id, db=db)


async def _routable_route_candidate(
    *,
    org_id: UUID,
    candidate: EffectiveAccessRouteCandidate,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
) -> ProviderRouteResource | None:
    resource = await provider_read_models.get_route_resource(
        org_id=org_id,
        provider_id=candidate.provider_id,
        credential_pool_id=candidate.credential_pool_id,
        model_offering_id=candidate.provider_model_offering_id or candidate.model_offering_id,
        db=db,
    )
    if not _route_resource_is_routable(resource):
        return None
    if not _provider_supports_gateway_endpoint(resource, gateway_endpoint):
        return None
    return resource


async def _match_policy_route(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    requested_model: str,
    provider_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
) -> list[ResolvedPolicyRoute]:
    candidates = await build_effective_access_routes_readonly(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    candidates.sort(key=lambda item: (item.priority, -item.weight, item.created_at))
    matches: list[ResolvedPolicyRoute] = []
    matched_public_model_id: UUID | None = None
    for candidate in candidates:
        if (
            matched_public_model_id is not None
            and candidate.public_model_id != matched_public_model_id
        ):
            continue
        if provider_id is not None and candidate.provider_id != provider_id:
            continue
        routable = await _routable_route_candidate(
            org_id=org_id,
            candidate=candidate,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        if routable is None:
            continue
        if requested_model != candidate.public_model_name:
            continue
        matched_public_model_id = candidate.public_model_id
        matches.append((candidate, routable))
        if candidate.routing_mode == "single_route":
            break
        if (
            candidate.max_route_attempts is not None
            and len(matches) >= candidate.max_route_attempts
        ):
            break
    return matches


async def _explain_route_candidates(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    plan: ResolvedAccessPlan | None,
    db: AsyncSession,
) -> list[RouteCandidateExplanation]:
    candidates = await build_effective_access_routes_readonly(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    )
    candidates.sort(key=lambda item: (item.priority, -item.weight, item.created_at))
    attempt_index_by_candidate = (
        {attempt.route_candidate_id: attempt.routing_attempt_index for attempt in plan.attempts}
        if plan is not None
        else {}
    )
    selected_candidate_id = plan.attempts[0].route_candidate_id if plan and plan.attempts else None
    explanations: list[RouteCandidateExplanation] = []
    for candidate_index, candidate in enumerate(candidates):
        model_id = candidate.provider_model_offering_id or candidate.model_offering_id
        resource = await provider_read_models.get_route_resource(
            org_id=virtual_key.org_id,
            provider_id=candidate.provider_id,
            credential_pool_id=candidate.credential_pool_id,
            model_offering_id=model_id,
            db=db,
        )
        attempt_index = attempt_index_by_candidate.get(candidate.route_candidate_id)
        skipped_reason, skipped_message = _route_candidate_skip_reason(
            candidate=candidate,
            resource=resource,
            requested_model=requested_model,
            provider_id=provider_id,
            gateway_endpoint=gateway_endpoint,
            plan=plan,
            attempt_index=attempt_index,
        )
        explanations.append(
            RouteCandidateExplanation(
                candidate_index=candidate_index,
                route_candidate_id=candidate.route_candidate_id,
                public_model_id=candidate.public_model_id,
                public_model_name=candidate.public_model_name,
                access_policy_id=candidate.shared_policy_id,
                access_policy_revision_id=candidate.policy_revision_id,
                assignment_id=candidate.assignment_id,
                provider_id=candidate.provider_id,
                provider_name=resource.provider_name,
                credential_pool_id=candidate.credential_pool_id,
                credential_pool_name=resource.credential_pool_name,
                provider_model_offering_id=model_id,
                provider_model=resource.provider_model_name,
                attempt_index=attempt_index,
                selected=candidate.route_candidate_id == selected_candidate_id,
                would_attempt=attempt_index is not None,
                skipped_reason=skipped_reason,
                skipped_message=skipped_message,
            )
        )
    return explanations


def _route_candidate_skip_reason(
    *,
    candidate: EffectiveAccessRouteCandidate,
    resource: ProviderRouteResource,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    plan: ResolvedAccessPlan | None,
    attempt_index: int | None,
) -> tuple[str | None, str | None]:
    if attempt_index is not None:
        return None, None
    if requested_model != candidate.public_model_name:
        return "requested_model_mismatch", "The public model name did not match the request."
    if provider_id is not None and candidate.provider_id != provider_id:
        return "provider_pinned_mismatch", "The request pinned a different provider."
    if not resource.provider_is_active:
        return "provider_inactive", "The provider is inactive or missing."
    if not resource.credential_pool_is_active:
        return "credential_pool_inactive", "The credential pool is inactive or missing."
    if not resource.model_is_active or resource.model_provider_id != candidate.provider_id:
        return "provider_model_offering_inactive", "The model offering is inactive or missing."
    if resource.credential_pool_provider_id != candidate.provider_id:
        return "credential_pool_inactive", "The credential pool belongs to a different provider."
    if not _provider_supports_gateway_endpoint(resource, gateway_endpoint):
        return "endpoint_incompatible", "The provider does not support this gateway endpoint."
    if plan is not None and candidate.public_model_name == plan.public_model_name:
        return (
            "routing_mode_disables_fallback",
            "The selected routing mode did not attempt this route.",
        )
    return "child_scope_narrowing_removed_candidate", "A narrower access scope removed this route."


def _route_resource_is_routable(resource: ProviderRouteResource) -> bool:
    return (
        resource.provider_is_active
        and resource.credential_pool_is_active
        and resource.model_is_active
        and resource.credential_pool_provider_id == resource.provider_id
        and resource.model_provider_id == resource.provider_id
        and resource.credential_pool_has_active_credential
    )


def _route_resource_is_inventory_ready(resource: ProviderRouteResource) -> bool:
    return (
        resource.credential_pool_is_active
        and resource.model_is_active
        and resource.credential_pool_provider_id == resource.provider_id
        and resource.model_provider_id == resource.provider_id
        and resource.credential_pool_has_active_credential
    )


def _provider_supports_gateway_endpoint(
    resource: ProviderRouteResource,
    gateway_endpoint: str | None,
) -> bool:
    if gateway_endpoint is None:
        return True
    if gateway_endpoint == "anthropic_messages":
        return bool(resource.provider_integration_capabilities.get("native_anthropic_messages"))
    if gateway_endpoint in {"chat_completions", "responses", "completions"}:
        return bool(resource.provider_integration_capabilities.get("openai_compatible_chat"))
    return True


async def build_effective_access_routes_readonly(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[EffectiveAccessRouteCandidate]:
    assignments = await policy_read_models.list_access_runtime_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    candidates = await policy_read_models.list_access_runtime_route_candidates_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    effective: list[EffectiveAccessRouteCandidate] | None = None
    for scope_type in ("org", "team", "project", "virtual_key"):
        scoped_assignments = [
            assignment for assignment in assignments if assignment.source_scope == scope_type
        ]
        if not scoped_assignments:
            continue
        assignment_ids = {assignment.assignment_id for assignment in scoped_assignments}
        scoped = [
            candidate for candidate in candidates if candidate.assignment_id in assignment_ids
        ]
        if effective is None:
            effective = scoped
            continue
        effective = [
            candidate
            for candidate in scoped
            if any(_route_candidate_matches(candidate, ancestor) for ancestor in effective)
        ]
    return effective or []


def _route_candidate_matches(
    child: EffectiveAccessRouteCandidate,
    ancestor: EffectiveAccessRouteCandidate,
) -> bool:
    return (
        child.public_model_name == ancestor.public_model_name
        and child.provider_id == ancestor.provider_id
        and child.credential_pool_id == ancestor.credential_pool_id
        and (child.provider_model_offering_id or child.model_offering_id)
        == (ancestor.provider_model_offering_id or ancestor.model_offering_id)
    )


def _accessible_model_id(*, candidate: EffectiveAccessRouteCandidate) -> str:
    return candidate.public_model_name


def _accessible_model_candidate(
    *,
    candidate: EffectiveAccessRouteCandidate,
    resource: ProviderRouteResource,
) -> AccessibleModelCandidate:
    return AccessibleModelCandidate(
        provider_id=resource.provider_id,
        provider_name=resource.provider_name or "Unknown provider",
        pool_id=resource.credential_pool_id,
        pool_name=resource.credential_pool_name or "",
        model_offering_id=resource.model_offering_id,
        provider_model=resource.provider_model_name or "",
        route_candidate_id=candidate.route_candidate_id,
        access_policy_route_id=None,
        priority=candidate.priority,
        weight=candidate.weight,
    )


def _to_resolved_limit_policy(rule: LimitRuleMatch):
    return ResolvedLimitPolicy(
        limit_policy_assignment_id=rule.assignment_id,
        limit_policy_id=rule.limit_policy_id,
        limit_policy_revision_id=rule.policy_revision_id,
        limit_policy_name=rule.policy_name,
        limit_policy_rule_id=rule.rule_id,
        name=rule.name,
        limit_type=rule.limit_type,
        limit_value=rule.limit_value,
        interval_unit=rule.interval_unit,
        interval_count=rule.interval_count,
    )


def _to_resolved_route_attempt(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    candidate: EffectiveAccessRouteCandidate,
    resource: ProviderRouteResource,
    attempt_index: int,
    primary_route_candidate_id: UUID,
    limit_rules: list[LimitRuleMatch],
) -> ResolvedRouteAttempt:
    return ResolvedRouteAttempt(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        access_policy_id=candidate.shared_policy_id,
        access_policy_revision_id=candidate.policy_revision_id,
        access_policy_assignment_id=candidate.assignment_id,
        access_policy_route_id=None,
        public_model_id=candidate.public_model_id,
        route_candidate_id=candidate.route_candidate_id,
        public_model_name=candidate.public_model_name,
        routing_mode=candidate.routing_mode,
        model_offering_id=resource.model_offering_id,
        virtual_key_id=virtual_key.id,
        provider_id=candidate.provider_id,
        pool_id=resource.credential_pool_id,
        provider_key_id=None,
        requested_model=requested_model,
        provider_model=resource.provider_model_name or "",
        routing_attempt_index=attempt_index,
        primary_route_candidate_id=primary_route_candidate_id,
        input_price_per_million_tokens=resource.effective_input_price_per_million_tokens,
        output_price_per_million_tokens=resource.effective_output_price_per_million_tokens,
        limit_policy_ids=list({rule.limit_policy_id for rule in limit_rules}),
        limit_policies=[_to_resolved_limit_policy(rule) for rule in limit_rules],
    )


async def _effective_access_policy_references(
    *, candidates: list[EffectiveAccessRouteCandidate]
) -> list[EffectivePolicyReference]:
    scope_order = {"org": 0, "team": 1, "project": 2, "virtual_key": 3}
    references: dict[UUID, EffectivePolicyReference] = {}
    for candidate in sorted(
        candidates, key=lambda item: scope_order.get(item.source_scope, -1), reverse=True
    ):
        references.setdefault(
            candidate.shared_policy_id,
            EffectivePolicyReference(
                id=candidate.shared_policy_id,
                name=candidate.policy_name,
                source_scope=candidate.source_scope,
            ),
        )
    return list(references.values())


async def _effective_limit_policy_references(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[EffectiveLimitReference]:
    references = await policy_read_models.list_limit_runtime_policy_references_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    effective: dict[UUID, EffectiveLimitReference] = {}
    for reference in references:
        effective.setdefault(
            reference.limit_policy_id,
            EffectiveLimitReference(
                id=reference.limit_policy_id,
                name=reference.policy_name,
                source_scope=reference.source_scope,
            ),
        )
    return list(effective.values())


async def _matching_limit_policies(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    route: EffectiveAccessRouteCandidate,
    db: AsyncSession,
) -> list[LimitRuleMatch]:
    rules = await policy_read_models.list_limit_runtime_rules_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    return [rule for rule in rules if _limit_rule_matches_candidate(rule=rule, candidate=route)]


def _limit_rule_matches_candidate(
    *,
    rule: LimitRuleMatch,
    candidate: EffectiveAccessRouteCandidate,
) -> bool:
    return (
        (rule.provider_id is None or rule.provider_id == candidate.provider_id)
        and (
            rule.credential_pool_id is None
            or rule.credential_pool_id == candidate.credential_pool_id
        )
        and (
            rule.model_offering_id is None
            or rule.model_offering_id == candidate.model_offering_id
        )
        and rule.access_policy_id in (None, candidate.access_policy_id)
    )


def _as_utc(value: datetime) -> datetime:
    return state.as_utc(value)
