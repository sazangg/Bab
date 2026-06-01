from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.policies.errors import PolicyNotFoundError, PolicyValidationError
from app.modules.policies.internal import repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    LimitPolicy,
    LimitPolicyRule,
    PolicyAssignment,
)
from app.modules.policies.schemas import (
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
        await db.delete(policy)


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
