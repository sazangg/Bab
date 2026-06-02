from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.keys import facade as keys_facade
from app.modules.policies.errors import PolicyNotFoundError, PolicyValidationError
from app.modules.policies.internal import repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyRoute,
    LimitPolicy,
    LimitPolicyRule,
    PolicyAssignment,
)
from app.modules.policies.schemas import (
    AccessPolicyModelOption,
    AccessPolicyOptionsResponse,
    AccessPolicyPoolOption,
    AccessPolicyProviderOption,
    AccessPolicyResponse,
    AccessPolicyRouteInput,
    AccessPolicyRouteResponse,
    CreateAccessPolicyRequest,
    CreateAccessPolicyRouteRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    LimitPolicyResponse,
    LimitPolicyRuleInput,
    LimitPolicyRuleResponse,
    PolicyAssignmentResponse,
    UpdateAccessPolicyRequest,
    UpdateAccessPolicyRouteRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError


async def list_access_policies(*, scope: Scope, db: AsyncSession) -> list[AccessPolicyResponse]:
    policies = await repository.list_access_policies(org_id=scope.org_id, db=db)
    return [await _access_policy_response(policy=policy, scope=scope, db=db) for policy in policies]


async def get_access_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> AccessPolicyResponse:
    policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def create_access_policy(
    *, payload: CreateAccessPolicyRequest, scope: Scope, db: AsyncSession
) -> AccessPolicyResponse:
    async with transaction(db):
        policy = await repository.create_access_policy(
            org_id=scope.org_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            db=db,
        )
        for route in payload.routes:
            await _validate_access_route(route=route, scope=scope, db=db)
            await repository.create_access_policy_route(
                org_id=scope.org_id,
                access_policy_id=policy.id,
                provider_id=route.provider_id,
                credential_pool_id=route.credential_pool_id,
                model_offering_ids=[str(model_id) for model_id in route.model_offering_ids],
                priority=route.priority,
                weight=route.weight,
                is_active=route.is_active,
                db=db,
            )
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def update_access_policy(
    *,
    policy_id: UUID,
    payload: UpdateAccessPolicyRequest,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyResponse:
    async with transaction(db):
        policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if payload.name is not None:
            policy.name = payload.name
        if payload.description is not None:
            policy.description = payload.description
        if payload.is_active is not None:
            policy.is_active = payload.is_active
        await db.flush()
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def delete_access_policy(*, policy_id: UUID, scope: Scope, db: AsyncSession) -> None:
    async with transaction(db):
        policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        await repository.delete_assignments_for_access_policy(
            org_id=scope.org_id, access_policy_id=policy.id, db=db
        )
        await db.delete(policy)


async def create_access_policy_route(
    *,
    policy_id: UUID,
    payload: CreateAccessPolicyRouteRequest,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyRouteResponse:
    async with transaction(db):
        await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        await _validate_access_route(route=payload, scope=scope, db=db)
        route = await repository.create_access_policy_route(
            org_id=scope.org_id,
            access_policy_id=policy_id,
            provider_id=payload.provider_id,
            credential_pool_id=payload.credential_pool_id,
            model_offering_ids=[str(model_id) for model_id in payload.model_offering_ids],
            priority=payload.priority,
            weight=payload.weight,
            is_active=payload.is_active,
            db=db,
        )
    return AccessPolicyRouteResponse.model_validate(route)


async def update_access_policy_route(
    *,
    route_id: UUID,
    payload: UpdateAccessPolicyRouteRequest,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyRouteResponse:
    async with transaction(db):
        route = await repository.get_access_policy_route(
            route_id=route_id, org_id=scope.org_id, db=db
        )
        if route is None:
            raise PolicyNotFoundError
        provider_id = payload.provider_id or route.provider_id
        pool_id = payload.credential_pool_id or route.credential_pool_id
        model_ids = payload.model_offering_ids or [
            UUID(str(item)) for item in route.model_offering_ids
        ]
        await _validate_access_route(
            route=AccessPolicyRouteInput(
                provider_id=provider_id,
                credential_pool_id=pool_id,
                model_offering_ids=model_ids,
            ),
            scope=scope,
            db=db,
        )
        if payload.provider_id is not None:
            route.provider_id = payload.provider_id
        if payload.credential_pool_id is not None:
            route.credential_pool_id = payload.credential_pool_id
        if payload.model_offering_ids is not None:
            route.model_offering_ids = [str(model_id) for model_id in payload.model_offering_ids]
        if payload.priority is not None:
            route.priority = payload.priority
        if payload.weight is not None:
            route.weight = payload.weight
        if payload.is_active is not None:
            route.is_active = payload.is_active
        await db.flush()
    return AccessPolicyRouteResponse.model_validate(route)


async def delete_access_policy_route(*, route_id: UUID, scope: Scope, db: AsyncSession) -> None:
    async with transaction(db):
        route = await repository.get_access_policy_route(
            route_id=route_id, org_id=scope.org_id, db=db
        )
        if route is None:
            raise PolicyNotFoundError
        await db.delete(route)


async def list_limit_policies(*, scope: Scope, db: AsyncSession) -> list[LimitPolicyResponse]:
    policies = await repository.list_limit_policies(org_id=scope.org_id, db=db)
    return [await _limit_policy_response(policy=policy, scope=scope, db=db) for policy in policies]


async def get_limit_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> LimitPolicyResponse:
    policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def create_limit_policy(
    *, payload: CreateLimitPolicyRequest, scope: Scope, db: AsyncSession
) -> LimitPolicyResponse:
    async with transaction(db):
        policy = await repository.create_limit_policy(
            org_id=scope.org_id,
            values=payload.model_dump(
                exclude={
                    "rules",
                    "budget_cents",
                    "max_requests",
                    "max_input_tokens",
                    "max_output_tokens",
                    "max_tokens_per_request",
                    "window",
                    "provider_id",
                    "credential_pool_id",
                    "model_offering_id",
                    "access_policy_id",
                }
            ),
            db=db,
        )
        rules = payload.rules or [_rule_from_legacy_limit_payload(payload)]
        for rule in rules:
            await _validate_limit_rule_filters(payload=rule, scope=scope, db=db)
            await repository.create_limit_policy_rule(
                org_id=scope.org_id,
                limit_policy_id=policy.id,
                values=rule.model_dump(),
                db=db,
            )
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def update_limit_policy(
    *,
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyResponse:
    values = payload.model_dump(exclude_unset=True)
    async with transaction(db):
        policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        for field, value in values.items():
            setattr(policy, field, value)
        await db.flush()
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def create_limit_policy_rule(
    *,
    policy_id: UUID,
    payload: CreateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyRuleResponse:
    await _validate_limit_rule_filters(payload=payload, scope=scope, db=db)
    async with transaction(db):
        await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        rule = await repository.create_limit_policy_rule(
            org_id=scope.org_id,
            limit_policy_id=policy_id,
            values=payload.model_dump(),
            db=db,
        )
    return LimitPolicyRuleResponse.model_validate(rule)


async def update_limit_policy_rule(
    *,
    rule_id: UUID,
    payload: UpdateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyRuleResponse:
    values = payload.model_dump(exclude_unset=True)
    async with transaction(db):
        rule = await _get_limit_policy_rule_or_raise(rule_id=rule_id, scope=scope, db=db)
        candidate = LimitPolicyRuleInput(
            name=values.get("name", rule.name),
            budget_cents=values.get("budget_cents", rule.budget_cents),
            max_requests=values.get("max_requests", rule.max_requests),
            max_input_tokens=values.get("max_input_tokens", rule.max_input_tokens),
            max_output_tokens=values.get("max_output_tokens", rule.max_output_tokens),
            max_tokens_per_request=values.get(
                "max_tokens_per_request", rule.max_tokens_per_request
            ),
            window=values.get("window", rule.window),
            provider_id=values.get("provider_id", rule.provider_id),
            credential_pool_id=values.get("credential_pool_id", rule.credential_pool_id),
            model_offering_id=values.get("model_offering_id", rule.model_offering_id),
            access_policy_id=values.get("access_policy_id", rule.access_policy_id),
            is_active=values.get("is_active", rule.is_active),
        )
        await _validate_limit_rule_filters(payload=candidate, scope=scope, db=db)
        for field, value in values.items():
            setattr(rule, field, value)
        await db.flush()
    return LimitPolicyRuleResponse.model_validate(rule)


async def delete_limit_policy_rule(*, rule_id: UUID, scope: Scope, db: AsyncSession) -> None:
    async with transaction(db):
        rule = await _get_limit_policy_rule_or_raise(rule_id=rule_id, scope=scope, db=db)
        await db.delete(rule)


async def delete_limit_policy(*, policy_id: UUID, scope: Scope, db: AsyncSession) -> None:
    async with transaction(db):
        policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        await repository.delete_assignments_for_limit_policy(
            org_id=scope.org_id, limit_policy_id=policy.id, db=db
        )
        await db.delete(policy)


async def get_access_policy_options(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    exclude_policy_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyOptionsResponse:
    parent_routes = await _parent_access_route_options(
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        exclude_policy_id=exclude_policy_id,
        scope=scope,
        db=db,
    )
    if parent_routes:
        return await _options_from_route_candidates(
            route_candidates=parent_routes,
            scope=scope,
            db=db,
        )
    return await _all_access_options(scope=scope, db=db)


async def list_policy_assignments(
    *, scope: Scope, db: AsyncSession
) -> list[PolicyAssignmentResponse]:
    assignments = await repository.list_policy_assignments(org_id=scope.org_id, db=db)
    return [PolicyAssignmentResponse.model_validate(assignment) for assignment in assignments]


async def create_policy_assignment(
    *, payload: CreatePolicyAssignmentRequest, scope: Scope, db: AsyncSession
) -> PolicyAssignmentResponse:
    await _validate_assignment_policy(payload=payload, scope=scope, db=db)
    async with transaction(db):
        assignment = await repository.create_policy_assignment(
            org_id=scope.org_id,
            values=payload.model_dump(),
            db=db,
        )
    return PolicyAssignmentResponse.model_validate(assignment)


async def update_policy_assignment(
    *,
    assignment_id: UUID,
    payload: UpdatePolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
) -> PolicyAssignmentResponse:
    async with transaction(db):
        assignment = await _get_policy_assignment_or_raise(
            assignment_id=assignment_id, scope=scope, db=db
        )
        if payload.is_active is not None:
            assignment.is_active = payload.is_active
        await db.flush()
    return PolicyAssignmentResponse.model_validate(assignment)


async def delete_policy_assignment(*, assignment_id: UUID, scope: Scope, db: AsyncSession) -> None:
    async with transaction(db):
        assignment = await _get_policy_assignment_or_raise(
            assignment_id=assignment_id, scope=scope, db=db
        )
        await db.delete(assignment)


async def _access_policy_response(
    *, policy: AccessPolicy, scope: Scope, db: AsyncSession
) -> AccessPolicyResponse:
    routes = await repository.list_access_policy_routes(
        org_id=scope.org_id, access_policy_id=policy.id, db=db
    )
    response = AccessPolicyResponse.model_validate(policy)
    response.routes = [AccessPolicyRouteResponse.model_validate(route) for route in routes]
    return response


async def _limit_policy_response(
    *, policy: LimitPolicy, scope: Scope, db: AsyncSession
) -> LimitPolicyResponse:
    rules = await repository.list_limit_policy_rules(
        org_id=scope.org_id, limit_policy_id=policy.id, db=db
    )
    response = LimitPolicyResponse.model_validate(policy)
    response.rules = [LimitPolicyRuleResponse.model_validate(rule) for rule in rules]
    return response


async def _get_access_policy_or_raise(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> AccessPolicy:
    policy = await repository.get_access_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise PolicyNotFoundError
    return policy


async def _get_limit_policy_or_raise(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> LimitPolicy:
    policy = await repository.get_limit_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise PolicyNotFoundError
    return policy


async def _get_limit_policy_rule_or_raise(
    *, rule_id: UUID, scope: Scope, db: AsyncSession
) -> LimitPolicyRule:
    rule = await repository.get_limit_policy_rule(rule_id=rule_id, org_id=scope.org_id, db=db)
    if rule is None:
        raise PolicyNotFoundError
    return rule


async def _get_policy_assignment_or_raise(
    *, assignment_id: UUID, scope: Scope, db: AsyncSession
) -> PolicyAssignment:
    assignment = await repository.get_policy_assignment(
        assignment_id=assignment_id, org_id=scope.org_id, db=db
    )
    if assignment is None:
        raise PolicyNotFoundError
    return assignment


async def _parent_access_route_options(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    exclude_policy_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> list[tuple[AccessPolicyRoute, UUID]]:
    if scope_type == "org":
        return []
    parent_scopes = ["org"] if scope_type == "team" else ["org", "team"]
    if scope_type == "virtual_key":
        parent_scopes.append("project")
    resolved_team_id = team_id
    if project_id is not None:
        project = await keys_facade.get_project(project_id=project_id, scope=scope, db=db)
        resolved_team_id = project.team_id
    assignments: list[PolicyAssignment] = []
    for parent_scope in parent_scopes:
        scoped = await repository.list_active_policy_assignments_for_scope(
            org_id=scope.org_id,
            scope_type=parent_scope,
            policy_type="access",
            db=db,
        )
        assignments.extend(
            assignment
            for assignment in scoped
            if _assignment_applies_to_parent(
                assignment=assignment,
                team_id=resolved_team_id,
                project_id=project_id,
            )
        )
    return await _effective_access_route_candidates(
        assignments=assignments,
        exclude_policy_id=exclude_policy_id,
        scope=scope,
        db=db,
    )


def _assignment_applies_to_parent(
    *,
    assignment: PolicyAssignment,
    team_id: UUID | None,
    project_id: UUID | None,
) -> bool:
    if assignment.scope_type == "org":
        return True
    if assignment.scope_type == "team":
        return team_id is not None and assignment.team_id == team_id
    if assignment.scope_type == "project":
        return project_id is not None and assignment.project_id == project_id
    return False


async def _effective_access_route_candidates(
    *,
    assignments: list[PolicyAssignment],
    exclude_policy_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> list[tuple[AccessPolicyRoute, UUID]]:
    effective: list[tuple[AccessPolicyRoute, UUID]] | None = None
    for scope_type in ("org", "team", "project"):
        candidates = await _access_route_candidates(
            assignments=[
                assignment
                for assignment in assignments
                if assignment.scope_type == scope_type
                and assignment.access_policy_id != exclude_policy_id
            ],
            scope=scope,
            db=db,
        )
        if not candidates:
            continue
        if effective is None:
            effective = candidates
            continue
        effective = [
            candidate
            for candidate in candidates
            if any(_route_candidate_matches(candidate, parent) for parent in effective)
        ]
    return effective or []


async def _access_route_candidates(
    *,
    assignments: list[PolicyAssignment],
    scope: Scope,
    db: AsyncSession,
) -> list[tuple[AccessPolicyRoute, UUID]]:
    candidates: list[tuple[AccessPolicyRoute, UUID]] = []
    for assignment in assignments:
        if assignment.access_policy_id is None:
            continue
        policy = await repository.get_access_policy(
            policy_id=assignment.access_policy_id,
            org_id=scope.org_id,
            db=db,
        )
        if policy is None or not policy.is_active:
            continue
        routes = await repository.list_access_policy_routes(
            org_id=scope.org_id,
            access_policy_id=policy.id,
            db=db,
        )
        for route in routes:
            if route.is_active:
                candidates.extend(
                    (route, UUID(str(model_id))) for model_id in route.model_offering_ids
                )
    return candidates


def _route_candidate_matches(
    child: tuple[AccessPolicyRoute, UUID],
    parent: tuple[AccessPolicyRoute, UUID],
) -> bool:
    child_route, child_model_id = child
    parent_route, parent_model_id = parent
    return (
        child_route.provider_id == parent_route.provider_id
        and child_route.credential_pool_id == parent_route.credential_pool_id
        and child_model_id == parent_model_id
    )


async def _all_access_options(*, scope: Scope, db: AsyncSession) -> AccessPolicyOptionsResponse:
    providers = await providers_facade.list_providers(scope=scope, db=db)
    groups: dict[UUID, AccessPolicyProviderOption] = {}
    for provider in providers:
        if not provider.is_active:
            continue
        pools = await providers_facade.list_credential_pools(
            provider_id=provider.id,
            scope=scope,
            db=db,
        )
        models = await providers_facade.list_model_offerings(
            provider_id=provider.id,
            search=None,
            modalities=None,
            is_active=True,
            limit=1000,
            offset=0,
            scope=scope,
            db=db,
        )
        pool_options = [
            AccessPolicyPoolOption(
                id=pool.id,
                name=pool.name,
                models=[
                    AccessPolicyModelOption(
                        id=model.id,
                        provider_model_name=model.provider_model_name,
                        alias=model.alias,
                    )
                    for model in models.items
                ],
            )
            for pool in pools
            if pool.is_active
        ]
        if pool_options:
            groups[provider.id] = AccessPolicyProviderOption(
                id=provider.id,
                display_name=provider.display_name or provider.name,
                pools=pool_options,
            )
    return AccessPolicyOptionsResponse(providers=list(groups.values()))


async def _options_from_route_candidates(
    *,
    route_candidates: list[tuple[AccessPolicyRoute, UUID]],
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyOptionsResponse:
    providers: dict[UUID, AccessPolicyProviderOption] = {}
    pools: dict[tuple[UUID, UUID], AccessPolicyPoolOption] = {}
    seen_models: set[tuple[UUID, UUID, UUID]] = set()
    for route, model_id in route_candidates:
        try:
            provider = await providers_facade.get_provider(
                provider_id=route.provider_id,
                scope=scope,
                db=db,
            )
            pool = await providers_facade.get_credential_pool(
                pool_id=route.credential_pool_id,
                scope=scope,
                db=db,
            )
            model = await providers_facade.get_model_offering(
                model_offering_id=model_id,
                scope=scope,
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if not provider.is_active or not pool.is_active or not model.is_active:
            continue
        provider_option = providers.setdefault(
            provider.id,
            AccessPolicyProviderOption(
                id=provider.id,
                display_name=provider.display_name or provider.name,
                pools=[],
            ),
        )
        pool_key = (provider.id, pool.id)
        pool_option = pools.get(pool_key)
        if pool_option is None:
            pool_option = AccessPolicyPoolOption(id=pool.id, name=pool.name, models=[])
            pools[pool_key] = pool_option
            provider_option.pools.append(pool_option)
        model_key = (provider.id, pool.id, model.id)
        if model_key in seen_models:
            continue
        seen_models.add(model_key)
        pool_option.models.append(
            AccessPolicyModelOption(
                id=model.id,
                provider_model_name=model.provider_model_name,
                alias=model.alias,
            )
        )
    return AccessPolicyOptionsResponse(providers=list(providers.values()))


async def _validate_access_route(
    *, route: AccessPolicyRouteInput, scope: Scope, db: AsyncSession
) -> None:
    try:
        provider = await providers_facade.get_provider(
            provider_id=route.provider_id, scope=scope, db=db
        )
        pool = await providers_facade.get_credential_pool(
            pool_id=route.credential_pool_id, scope=scope, db=db
        )
        if pool.provider_id != provider.id:
            raise PolicyValidationError
        for model_id in route.model_offering_ids:
            model = await providers_facade.get_model_offering(
                model_offering_id=model_id, scope=scope, db=db
            )
            if model.provider_id != provider.id:
                raise PolicyValidationError
    except ProviderNotFoundError as exc:
        raise PolicyValidationError from exc


async def _validate_limit_rule_filters(
    *, payload: LimitPolicyRuleInput, scope: Scope, db: AsyncSession
) -> None:
    try:
        if payload.provider_id is not None:
            await providers_facade.get_provider(
                provider_id=payload.provider_id, scope=scope, db=db
            )
        if payload.credential_pool_id is not None:
            await providers_facade.get_credential_pool(
                pool_id=payload.credential_pool_id, scope=scope, db=db
            )
        if payload.model_offering_id is not None:
            await providers_facade.get_model_offering(
                model_offering_id=payload.model_offering_id, scope=scope, db=db
            )
        if payload.access_policy_id is not None:
            await _get_access_policy_or_raise(
                policy_id=payload.access_policy_id, scope=scope, db=db
            )
    except (ProviderNotFoundError, PolicyNotFoundError) as exc:
        raise PolicyValidationError from exc


def _rule_from_legacy_limit_payload(payload: CreateLimitPolicyRequest) -> LimitPolicyRuleInput:
    return LimitPolicyRuleInput(
        name="Default rule",
        budget_cents=payload.budget_cents,
        max_requests=payload.max_requests,
        max_input_tokens=payload.max_input_tokens,
        max_output_tokens=payload.max_output_tokens,
        max_tokens_per_request=payload.max_tokens_per_request,
        window=payload.window,
        provider_id=payload.provider_id,
        credential_pool_id=payload.credential_pool_id,
        model_offering_id=payload.model_offering_id,
        access_policy_id=payload.access_policy_id,
        is_active=payload.is_active,
    )


async def _validate_assignment_policy(
    *, payload: CreatePolicyAssignmentRequest, scope: Scope, db: AsyncSession
) -> None:
    if payload.policy_type == "access" and payload.access_policy_id is not None:
        await _get_access_policy_or_raise(policy_id=payload.access_policy_id, scope=scope, db=db)
        return
    if payload.policy_type == "limit" and payload.limit_policy_id is not None:
        await _get_limit_policy_or_raise(policy_id=payload.limit_policy_id, scope=scope, db=db)
        return
    raise PolicyValidationError
