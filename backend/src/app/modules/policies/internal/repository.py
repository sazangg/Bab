from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyRoute,
    LimitPolicy,
    LimitPolicyRule,
    PolicyAssignment,
)


async def create_access_policy(
    *,
    org_id: UUID,
    name: str,
    description: str | None,
    is_active: bool,
    db: AsyncSession,
) -> AccessPolicy:
    policy = AccessPolicy(
        org_id=org_id,
        name=name,
        description=description,
        is_active=is_active,
    )
    db.add(policy)
    await db.flush()
    return policy


async def list_access_policies(*, org_id: UUID, db: AsyncSession) -> list[AccessPolicy]:
    result = await db.scalars(
        select(AccessPolicy)
        .where(AccessPolicy.org_id == org_id)
        .order_by(AccessPolicy.created_at.desc())
    )
    return list(result)


async def get_access_policy(
    *, policy_id: UUID, org_id: UUID, db: AsyncSession
) -> AccessPolicy | None:
    return await db.scalar(
        select(AccessPolicy).where(AccessPolicy.id == policy_id, AccessPolicy.org_id == org_id)
    )


async def create_access_policy_route(
    *,
    org_id: UUID,
    access_policy_id: UUID,
    provider_id: UUID,
    credential_pool_id: UUID,
    model_offering_ids: list[str],
    priority: int,
    weight: int,
    is_active: bool,
    db: AsyncSession,
) -> AccessPolicyRoute:
    route = AccessPolicyRoute(
        org_id=org_id,
        access_policy_id=access_policy_id,
        provider_id=provider_id,
        credential_pool_id=credential_pool_id,
        model_offering_ids=model_offering_ids,
        priority=priority,
        weight=weight,
        is_active=is_active,
    )
    db.add(route)
    await db.flush()
    return route


async def list_access_policy_routes(
    *, org_id: UUID, access_policy_id: UUID, db: AsyncSession
) -> list[AccessPolicyRoute]:
    result = await db.scalars(
        select(AccessPolicyRoute)
        .where(
            AccessPolicyRoute.org_id == org_id,
            AccessPolicyRoute.access_policy_id == access_policy_id,
        )
        .order_by(AccessPolicyRoute.priority, AccessPolicyRoute.created_at)
    )
    return list(result)


async def get_access_policy_route(
    *, route_id: UUID, org_id: UUID, db: AsyncSession
) -> AccessPolicyRoute | None:
    return await db.scalar(
        select(AccessPolicyRoute).where(
            AccessPolicyRoute.id == route_id,
            AccessPolicyRoute.org_id == org_id,
        )
    )


async def create_limit_policy(
    *,
    org_id: UUID,
    values: dict,
    db: AsyncSession,
) -> LimitPolicy:
    policy = LimitPolicy(org_id=org_id, **values)
    db.add(policy)
    await db.flush()
    return policy


async def list_limit_policies(*, org_id: UUID, db: AsyncSession) -> list[LimitPolicy]:
    result = await db.scalars(
        select(LimitPolicy)
        .where(LimitPolicy.org_id == org_id)
        .order_by(LimitPolicy.created_at.desc())
    )
    return list(result)


async def get_limit_policy(
    *, policy_id: UUID, org_id: UUID, db: AsyncSession
) -> LimitPolicy | None:
    return await db.scalar(
        select(LimitPolicy).where(LimitPolicy.id == policy_id, LimitPolicy.org_id == org_id)
    )


async def create_limit_policy_rule(
    *,
    org_id: UUID,
    limit_policy_id: UUID,
    values: dict,
    db: AsyncSession,
) -> LimitPolicyRule:
    rule = LimitPolicyRule(org_id=org_id, limit_policy_id=limit_policy_id, **values)
    db.add(rule)
    await db.flush()
    return rule


async def list_limit_policy_rules(
    *, org_id: UUID, limit_policy_id: UUID, db: AsyncSession
) -> list[LimitPolicyRule]:
    result = await db.scalars(
        select(LimitPolicyRule)
        .where(
            LimitPolicyRule.org_id == org_id,
            LimitPolicyRule.limit_policy_id == limit_policy_id,
        )
        .order_by(LimitPolicyRule.created_at.asc())
    )
    return list(result)


async def get_limit_policy_rule(
    *, rule_id: UUID, org_id: UUID, db: AsyncSession
) -> LimitPolicyRule | None:
    return await db.scalar(
        select(LimitPolicyRule).where(
            LimitPolicyRule.id == rule_id,
            LimitPolicyRule.org_id == org_id,
        )
    )


async def create_policy_assignment(
    *,
    org_id: UUID,
    values: dict,
    db: AsyncSession,
) -> PolicyAssignment:
    assignment = PolicyAssignment(org_id=org_id, **values)
    db.add(assignment)
    await db.flush()
    return assignment


async def list_policy_assignments(*, org_id: UUID, db: AsyncSession) -> list[PolicyAssignment]:
    result = await db.scalars(
        select(PolicyAssignment)
        .where(PolicyAssignment.org_id == org_id)
        .order_by(PolicyAssignment.created_at.desc())
    )
    return list(result)


async def list_active_policy_assignments_for_targets(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    policy_type: str,
    db: AsyncSession,
) -> list[PolicyAssignment]:
    target_filters = [
        PolicyAssignment.scope_type == "org",
        PolicyAssignment.team_id == team_id,
        PolicyAssignment.project_id == project_id,
    ]
    if virtual_key_id is not None:
        target_filters.append(PolicyAssignment.virtual_key_id == virtual_key_id)
    result = await db.scalars(
        select(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.is_active.is_(True),
            or_(*target_filters),
        )
        .order_by(PolicyAssignment.created_at)
    )
    return list(result)


async def get_policy_assignment(
    *, assignment_id: UUID, org_id: UUID, db: AsyncSession
) -> PolicyAssignment | None:
    return await db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.id == assignment_id,
            PolicyAssignment.org_id == org_id,
        )
    )
