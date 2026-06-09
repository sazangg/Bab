from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Team
from app.modules.keys.internal.models import Project, VirtualKey
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
    owning_scope_type: str | None = None,
    owning_team_id: UUID | None = None,
    owning_project_id: UUID | None = None,
    owning_virtual_key_id: UUID | None = None,
    db: AsyncSession,
) -> AccessPolicy:
    policy = AccessPolicy(
        org_id=org_id,
        name=name,
        description=description,
        is_active=is_active,
        owning_scope_type=owning_scope_type,
        owning_team_id=owning_team_id,
        owning_project_id=owning_project_id,
        owning_virtual_key_id=owning_virtual_key_id,
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


async def find_active_policy_assignment_for_scope(
    *,
    org_id: UUID,
    policy_type: str,
    access_policy_id: UUID | None,
    limit_policy_id: UUID | None,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> PolicyAssignment | None:
    return await db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.access_policy_id.is_(None)
            if access_policy_id is None
            else PolicyAssignment.access_policy_id == access_policy_id,
            PolicyAssignment.limit_policy_id.is_(None)
            if limit_policy_id is None
            else PolicyAssignment.limit_policy_id == limit_policy_id,
            PolicyAssignment.scope_type == scope_type,
            PolicyAssignment.team_id.is_(None)
            if team_id is None
            else PolicyAssignment.team_id == team_id,
            PolicyAssignment.project_id.is_(None)
            if project_id is None
            else PolicyAssignment.project_id == project_id,
            PolicyAssignment.virtual_key_id.is_(None)
            if virtual_key_id is None
            else PolicyAssignment.virtual_key_id == virtual_key_id,
            PolicyAssignment.is_active.is_(True),
        )
    )


async def get_team(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> Team | None:
    return await db.scalar(select(Team).where(Team.org_id == org_id, Team.id == team_id))


async def get_project(*, org_id: UUID, project_id: UUID, db: AsyncSession) -> Project | None:
    return await db.scalar(
        select(Project).where(Project.org_id == org_id, Project.id == project_id)
    )


async def get_virtual_key(
    *, org_id: UUID, virtual_key_id: UUID, db: AsyncSession
) -> VirtualKey | None:
    return await db.scalar(
        select(VirtualKey).where(VirtualKey.org_id == org_id, VirtualKey.id == virtual_key_id)
    )


async def list_policy_assignments(*, org_id: UUID, db: AsyncSession) -> list[PolicyAssignment]:
    result = await db.scalars(
        select(PolicyAssignment)
        .where(PolicyAssignment.org_id == org_id)
        .order_by(PolicyAssignment.created_at.desc())
    )
    return list(result)


async def delete_assignments_for_access_policy(
    *, org_id: UUID, access_policy_id: UUID, db: AsyncSession
) -> None:
    await db.execute(
        delete(PolicyAssignment).where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.access_policy_id == access_policy_id,
        )
    )


async def delete_assignments_for_limit_policy(
    *, org_id: UUID, limit_policy_id: UUID, db: AsyncSession
) -> None:
    await db.execute(
        delete(PolicyAssignment).where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.limit_policy_id == limit_policy_id,
        )
    )


async def list_active_policy_assignments_for_scope(
    *,
    org_id: UUID,
    scope_type: str,
    policy_type: str,
    db: AsyncSession,
) -> list[PolicyAssignment]:
    result = await db.scalars(
        select(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.scope_type == scope_type,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.is_active.is_(True),
        )
        .order_by(PolicyAssignment.created_at)
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


async def list_policy_assignments_for_access_policy(
    *, org_id: UUID, access_policy_id: UUID, active_only: bool, db: AsyncSession
) -> list[PolicyAssignment]:
    filters = [
        PolicyAssignment.org_id == org_id,
        PolicyAssignment.access_policy_id == access_policy_id,
    ]
    if active_only:
        filters.append(PolicyAssignment.is_active.is_(True))
    result = await db.scalars(select(PolicyAssignment).where(*filters))
    return list(result)


async def list_policy_assignments_for_limit_policy(
    *, org_id: UUID, limit_policy_id: UUID, active_only: bool, db: AsyncSession
) -> list[PolicyAssignment]:
    filters = [
        PolicyAssignment.org_id == org_id,
        PolicyAssignment.limit_policy_id == limit_policy_id,
    ]
    if active_only:
        filters.append(PolicyAssignment.is_active.is_(True))
    result = await db.scalars(select(PolicyAssignment).where(*filters))
    return list(result)


async def list_virtual_keys_for_project_ids(
    *, org_id: UUID, project_ids: list[UUID], db: AsyncSession
) -> list[tuple[VirtualKey, Project]]:
    if not project_ids:
        return []
    rows = await db.execute(
        select(VirtualKey, Project)
        .join(Project, Project.id == VirtualKey.project_id)
        .where(
            VirtualKey.org_id == org_id,
            Project.org_id == org_id,
            VirtualKey.project_id.in_(project_ids),
            VirtualKey.revoked_at.is_(None),
            or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
        )
        .order_by(Project.name, VirtualKey.name)
    )
    return list(rows.all())


async def list_virtual_keys_by_ids(
    *, org_id: UUID, virtual_key_ids: list[UUID], db: AsyncSession
) -> list[tuple[VirtualKey, Project]]:
    if not virtual_key_ids:
        return []
    rows = await db.execute(
        select(VirtualKey, Project)
        .join(Project, Project.id == VirtualKey.project_id)
        .where(
            VirtualKey.org_id == org_id,
            Project.org_id == org_id,
            VirtualKey.id.in_(virtual_key_ids),
        )
        .order_by(Project.name, VirtualKey.name)
    )
    return list(rows.all())


async def list_projects_for_team_ids(
    *, org_id: UUID, team_ids: list[UUID], db: AsyncSession
) -> list[Project]:
    if not team_ids:
        return []
    result = await db.scalars(
        select(Project)
        .where(Project.org_id == org_id, Project.team_id.in_(team_ids))
        .order_by(Project.name)
    )
    return list(result)


async def list_all_projects(*, org_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.org_id == org_id).order_by(Project.name)
    )
    return list(result)
