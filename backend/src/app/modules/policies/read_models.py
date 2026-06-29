from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.policy_kernel.models import Policy, PolicyAssignment, PolicyRevision


class ProviderPolicyRouteImpact(BaseModel):
    policy_id: UUID
    policy_name: str
    route_id: UUID


class PolicyLabel(BaseModel):
    id: UUID
    name: str
    kind: str


class AccessRuntimeRouteCandidate(BaseModel):
    assignment_id: UUID
    shared_policy_id: UUID
    policy_name: str
    source_scope: str
    assignment_team_id: UUID | None
    assignment_project_id: UUID | None
    assignment_virtual_key_id: UUID | None
    access_policy_id: UUID | None
    policy_revision_id: UUID
    public_model_id: UUID
    public_model_name: str
    routing_mode: str
    fallback_on: list[str]
    max_route_attempts: int | None
    route_candidate_id: UUID
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_id: UUID
    provider_model_offering_id: UUID | None
    priority: int
    weight: int
    created_at: datetime


class AccessRuntimeAssignment(BaseModel):
    assignment_id: UUID
    shared_policy_id: UUID
    policy_name: str
    source_scope: str


class LimitRuntimeRule(BaseModel):
    assignment_id: UUID
    shared_policy_id: UUID
    source_scope: str
    limit_policy_id: UUID
    policy_revision_id: UUID
    policy_name: str
    rule_id: UUID
    name: str
    limit_type: str
    limit_value: int
    interval_unit: str
    interval_count: int
    provider_id: UUID | None
    credential_pool_id: UUID | None
    model_offering_id: UUID | None
    access_policy_id: UUID | None


class LimitRuntimePolicyReference(BaseModel):
    assignment_id: UUID
    shared_policy_id: UUID
    source_scope: str
    limit_policy_id: UUID
    policy_name: str


class LimitBudgetRuleReference(BaseModel):
    limit_policy_id: UUID
    limit_policy_name: str
    limit_policy_rule_id: UUID
    rule_name: str
    interval_unit: str
    interval_count: int
    budget_cents: int


async def list_access_runtime_route_candidates_for_targets(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[AccessRuntimeRouteCandidate]:
    assignments = await _list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="access",
        db=db,
    )
    return await _access_runtime_route_candidates_for_assignments(
        org_id=org_id,
        assignments=assignments,
        db=db,
    )


async def list_access_runtime_assignments_for_targets(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[AccessRuntimeAssignment]:
    assignments = await _list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="access",
        db=db,
    )
    return await _access_runtime_assignments(org_id=org_id, assignments=assignments, db=db)


async def list_access_inventory_route_candidates_for_targets(
    *,
    org_id: UUID,
    team_ids: set[UUID],
    project_ids: set[UUID],
    virtual_key_ids: set[UUID],
    db: AsyncSession,
) -> list[AccessRuntimeRouteCandidate]:
    assignments = await _list_active_policy_assignments_for_inventory_targets(
        org_id=org_id,
        team_ids=team_ids,
        project_ids=project_ids,
        virtual_key_ids=virtual_key_ids,
        policy_type="access",
        db=db,
    )
    return await _access_runtime_route_candidates_for_assignments(
        org_id=org_id,
        assignments=assignments,
        db=db,
    )


async def list_limit_runtime_rules_for_targets(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[LimitRuntimeRule]:
    assignments = await _list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    if not assignments:
        return []
    policy_ids = _policy_ids_for_assignments(assignments)
    rows = await db.execute(
        select(Policy.id, LimitPolicy, PolicyRevision, LimitPolicyRule)
        .join(LimitPolicy, LimitPolicy.policy_id == Policy.id)
        .join(
            PolicyRevision,
            and_(
                PolicyRevision.policy_id == Policy.id,
                PolicyRevision.status == "active",
            ),
        )
        .join(
            LimitPolicyRule,
            and_(
                LimitPolicyRule.limit_policy_id == LimitPolicy.id,
                LimitPolicyRule.policy_revision_id == PolicyRevision.id,
            ),
        )
        .where(
            Policy.org_id == org_id,
            Policy.id.in_(policy_ids),
            Policy.kind == "limit",
            Policy.is_active.is_(True),
            LimitPolicy.org_id == org_id,
            LimitPolicy.is_active.is_(True),
            LimitPolicyRule.org_id == org_id,
            LimitPolicyRule.is_active.is_(True),
        )
        .order_by(Policy.id, LimitPolicyRule.created_at.asc())
    )
    rows_by_policy_id: dict[UUID, list[tuple[LimitPolicy, PolicyRevision, LimitPolicyRule]]] = (
        defaultdict(list)
    )
    for policy_id, policy, revision, rule in rows:
        rows_by_policy_id[policy_id].append((policy, revision, rule))
    rules: list[LimitRuntimeRule] = []
    for assignment in assignments:
        for policy, revision, rule in rows_by_policy_id.get(assignment.policy_id, []):
            rules.append(
                LimitRuntimeRule(
                    assignment_id=assignment.id,
                    shared_policy_id=assignment.policy_id,
                    source_scope=assignment.scope_type,
                    limit_policy_id=policy.id,
                    policy_revision_id=revision.id,
                    policy_name=policy.name,
                    rule_id=rule.id,
                    name=rule.name,
                    limit_type=rule.limit_type,
                    limit_value=rule.limit_value,
                    interval_unit=rule.interval_unit,
                    interval_count=rule.interval_count,
                    provider_id=rule.provider_id,
                    credential_pool_id=rule.credential_pool_id,
                    model_offering_id=rule.model_offering_id,
                    access_policy_id=rule.access_policy_id,
                )
            )
    return rules


async def list_limit_runtime_policy_references_for_targets(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[LimitRuntimePolicyReference]:
    assignments = await _list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    if not assignments:
        return []
    policy_ids = _policy_ids_for_assignments(assignments)
    rows = await db.execute(
        select(Policy.id, LimitPolicy)
        .join(LimitPolicy, LimitPolicy.policy_id == Policy.id)
        .where(
            Policy.org_id == org_id,
            Policy.id.in_(policy_ids),
            Policy.kind == "limit",
            Policy.is_active.is_(True),
            LimitPolicy.org_id == org_id,
            LimitPolicy.is_active.is_(True),
        )
    )
    policies_by_policy_id: dict[UUID, list[LimitPolicy]] = defaultdict(list)
    for policy_id, policy in rows:
        policies_by_policy_id[policy_id].append(policy)
    references: list[LimitRuntimePolicyReference] = []
    for assignment in assignments:
        for policy in policies_by_policy_id.get(assignment.policy_id, []):
            references.append(
                LimitRuntimePolicyReference(
                    assignment_id=assignment.id,
                    shared_policy_id=assignment.policy_id,
                    source_scope=assignment.scope_type,
                    limit_policy_id=policy.id,
                    policy_name=policy.name,
                )
            )
    return references


async def list_provider_route_impacts(
    *,
    org_id: UUID,
    db: AsyncSession,
    provider_id: UUID | None = None,
    credential_pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
) -> list[ProviderPolicyRouteImpact]:
    filters = _route_filters(
        org_id=org_id,
        provider_id=provider_id,
        credential_pool_id=credential_pool_id,
        model_offering_id=model_offering_id,
    )
    rows = await db.execute(
        select(AccessPolicy.id, AccessPolicy.name, AccessPolicyRouteCandidate.id)
        .join(
            AccessPolicyPublicModel,
            AccessPolicyPublicModel.access_policy_id == AccessPolicy.id,
        )
        .join(
            AccessPolicyRouteCandidate,
            AccessPolicyRouteCandidate.public_model_id == AccessPolicyPublicModel.id,
        )
        .where(*filters)
        .order_by(AccessPolicy.name)
    )
    return [
        ProviderPolicyRouteImpact(policy_id=policy_id, policy_name=name, route_id=route_id)
        for policy_id, name, route_id in rows
    ]


async def get_policy_labels(
    *,
    org_id: UUID,
    policy_ids: set[UUID],
    db: AsyncSession,
) -> dict[UUID, PolicyLabel]:
    if not policy_ids:
        return {}
    result = await db.scalars(
        select(Policy).where(
            Policy.org_id == org_id,
            Policy.id.in_(policy_ids),
        )
    )
    return {
        policy.id: PolicyLabel(
            id=policy.id,
            name=policy.name,
            kind=policy.kind,
        )
        for policy in result
    }


async def list_limit_budget_rule_references(
    *,
    org_id: UUID,
    db: AsyncSession,
) -> list[LimitBudgetRuleReference]:
    rows = await db.execute(
        select(
            LimitPolicy.id,
            LimitPolicy.name,
            LimitPolicyRule.id,
            LimitPolicyRule.name,
            LimitPolicyRule.interval_unit,
            LimitPolicyRule.interval_count,
            LimitPolicyRule.limit_value,
        )
        .join(LimitPolicy, LimitPolicy.id == LimitPolicyRule.limit_policy_id)
        .where(
            LimitPolicyRule.org_id == org_id,
            LimitPolicyRule.limit_type == "budget_cents",
            LimitPolicyRule.is_active.is_(True),
            LimitPolicy.is_active.is_(True),
        )
        .order_by(LimitPolicyRule.name.asc())
    )
    return [
        LimitBudgetRuleReference(
            limit_policy_id=limit_policy_id,
            limit_policy_name=limit_policy_name,
            limit_policy_rule_id=limit_policy_rule_id,
            rule_name=rule_name,
            interval_unit=interval_unit,
            interval_count=interval_count,
            budget_cents=int(budget_cents),
        )
        for (
            limit_policy_id,
            limit_policy_name,
            limit_policy_rule_id,
            rule_name,
            interval_unit,
            interval_count,
            budget_cents,
        ) in rows
    ]


async def count_provider_limit_rules(
    *,
    org_id: UUID,
    db: AsyncSession,
    provider_id: UUID | None = None,
    credential_pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
) -> int:
    filters = [
        LimitPolicyRule.org_id == org_id,
        LimitPolicyRule.is_active.is_(True),
    ]
    if provider_id is not None:
        filters.append(LimitPolicyRule.provider_id == provider_id)
    if credential_pool_id is not None:
        filters.append(LimitPolicyRule.credential_pool_id == credential_pool_id)
    if model_offering_id is not None:
        filters.append(LimitPolicyRule.model_offering_id == model_offering_id)
    return int(await db.scalar(select(func.count(LimitPolicyRule.id)).where(*filters)) or 0)


def _route_filters(
    *,
    org_id: UUID,
    provider_id: UUID | None,
    credential_pool_id: UUID | None,
    model_offering_id: UUID | None,
):
    filters = [
        AccessPolicy.org_id == org_id,
        AccessPolicy.is_active.is_(True),
        AccessPolicyPublicModel.is_active.is_(True),
        AccessPolicyRouteCandidate.is_active.is_(True),
    ]
    if provider_id is not None:
        filters.append(AccessPolicyRouteCandidate.provider_id == provider_id)
    if credential_pool_id is not None:
        filters.append(AccessPolicyRouteCandidate.credential_pool_id == credential_pool_id)
    if model_offering_id is not None:
        filters.append(AccessPolicyRouteCandidate.model_offering_id == model_offering_id)
    return filters


async def _access_runtime_route_candidates_for_assignments(
    *,
    org_id: UUID,
    assignments: list[PolicyAssignment],
    db: AsyncSession,
) -> list[AccessRuntimeRouteCandidate]:
    if not assignments:
        return []
    policy_ids = _policy_ids_for_assignments(assignments)
    rows = await db.execute(
        select(Policy, PolicyRevision, AccessPolicyPublicModel, AccessPolicyRouteCandidate)
        .join(
            PolicyRevision,
            and_(
                PolicyRevision.policy_id == Policy.id,
                PolicyRevision.status == "active",
            ),
        )
        .join(
            AccessPolicyPublicModel,
            and_(
                AccessPolicyPublicModel.policy_revision_id == PolicyRevision.id,
                AccessPolicyPublicModel.org_id == org_id,
                AccessPolicyPublicModel.is_active.is_(True),
            ),
        )
        .join(
            AccessPolicyRouteCandidate,
            AccessPolicyRouteCandidate.public_model_id == AccessPolicyPublicModel.id,
        )
        .where(
            Policy.org_id == org_id,
            Policy.id.in_(policy_ids),
            Policy.kind == "access",
            Policy.is_active.is_(True),
            AccessPolicyRouteCandidate.org_id == org_id,
            AccessPolicyRouteCandidate.is_active.is_(True),
        )
        .order_by(
            Policy.id,
            AccessPolicyPublicModel.created_at.asc(),
            AccessPolicyRouteCandidate.priority,
            AccessPolicyRouteCandidate.weight.desc(),
            AccessPolicyRouteCandidate.created_at,
        )
    )
    rows_by_policy_id: dict[
        UUID,
        list[tuple[Policy, PolicyRevision, AccessPolicyPublicModel, AccessPolicyRouteCandidate]],
    ] = defaultdict(list)
    for policy, revision, public_model, route_candidate in rows:
        rows_by_policy_id[policy.id].append((policy, revision, public_model, route_candidate))
    candidates: list[AccessRuntimeRouteCandidate] = []
    for assignment in assignments:
        for policy, revision, public_model, route_candidate in rows_by_policy_id.get(
            assignment.policy_id,
            [],
        ):
            candidates.append(
                AccessRuntimeRouteCandidate(
                    assignment_id=assignment.id,
                    shared_policy_id=assignment.policy_id,
                    policy_name=policy.name,
                    source_scope=assignment.scope_type,
                    assignment_team_id=assignment.team_id,
                    assignment_project_id=assignment.project_id,
                    assignment_virtual_key_id=assignment.virtual_key_id,
                    access_policy_id=public_model.access_policy_id,
                    policy_revision_id=revision.id,
                    public_model_id=public_model.id,
                    public_model_name=public_model.public_model_name,
                    routing_mode=public_model.routing_mode,
                    fallback_on=public_model.fallback_on,
                    max_route_attempts=public_model.max_route_attempts,
                    route_candidate_id=route_candidate.id,
                    provider_id=route_candidate.provider_id,
                    credential_pool_id=route_candidate.credential_pool_id,
                    model_offering_id=route_candidate.model_offering_id,
                    provider_model_offering_id=route_candidate.provider_model_offering_id,
                    priority=route_candidate.priority,
                    weight=route_candidate.weight,
                    created_at=route_candidate.created_at,
                )
            )
    return candidates


async def _access_runtime_assignments(
    *,
    org_id: UUID,
    assignments: list[PolicyAssignment],
    db: AsyncSession,
) -> list[AccessRuntimeAssignment]:
    if not assignments:
        return []
    policy_ids = _policy_ids_for_assignments(assignments)
    rows = await db.execute(
        select(Policy.id, Policy.name)
        .join(
            PolicyRevision,
            and_(
                PolicyRevision.policy_id == Policy.id,
                PolicyRevision.status == "active",
            ),
        )
        .where(
            Policy.org_id == org_id,
            Policy.id.in_(policy_ids),
            Policy.kind == "access",
            Policy.is_active.is_(True),
            PolicyRevision.org_id == org_id,
        )
        .order_by(Policy.id, PolicyRevision.created_at)
    )
    policy_names_by_id: dict[UUID, str] = {}
    for policy_id, policy_name in rows:
        policy_names_by_id.setdefault(policy_id, policy_name)
    runtime_assignments: list[AccessRuntimeAssignment] = []
    for assignment in assignments:
        policy_name = policy_names_by_id.get(assignment.policy_id)
        if policy_name is None:
            continue
        runtime_assignments.append(
            AccessRuntimeAssignment(
                assignment_id=assignment.id,
                shared_policy_id=assignment.policy_id,
                policy_name=policy_name,
                source_scope=assignment.scope_type,
            )
        )
    return runtime_assignments


def _policy_ids_for_assignments(assignments: list[PolicyAssignment]) -> set[UUID]:
    return {assignment.policy_id for assignment in assignments}


async def _list_active_policy_assignments_for_targets(
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
        and_(PolicyAssignment.scope_type == "team", PolicyAssignment.team_id == team_id),
        and_(PolicyAssignment.scope_type == "project", PolicyAssignment.project_id == project_id),
    ]
    if virtual_key_id is not None:
        target_filters.append(
            and_(
                PolicyAssignment.scope_type == "virtual_key",
                PolicyAssignment.virtual_key_id == virtual_key_id,
            )
        )
    return await _list_active_policy_assignments(
        org_id=org_id,
        policy_type=policy_type,
        target_filter=or_(*target_filters),
        db=db,
    )


async def _list_active_policy_assignments_for_inventory_targets(
    *,
    org_id: UUID,
    team_ids: set[UUID],
    project_ids: set[UUID],
    virtual_key_ids: set[UUID],
    policy_type: str,
    db: AsyncSession,
) -> list[PolicyAssignment]:
    return await _list_active_policy_assignments(
        org_id=org_id,
        policy_type=policy_type,
        target_filter=or_(
            PolicyAssignment.scope_type == "org",
            PolicyAssignment.team_id.in_(team_ids),
            PolicyAssignment.project_id.in_(project_ids),
            PolicyAssignment.virtual_key_id.in_(virtual_key_ids),
        ),
        db=db,
    )


async def _list_active_policy_assignments(
    *,
    org_id: UUID,
    policy_type: str,
    target_filter,
    db: AsyncSession,
) -> list[PolicyAssignment]:
    now = datetime.now(UTC)
    result = await db.scalars(
        select(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.is_active.is_(True),
            or_(PolicyAssignment.effective_from.is_(None), PolicyAssignment.effective_from <= now),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
            target_filter,
        )
        .order_by(PolicyAssignment.created_at)
    )
    return list(result)
