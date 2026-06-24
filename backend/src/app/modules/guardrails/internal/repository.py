from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.guardrails.internal.models import (
    GuardrailEvent,
    GuardrailPolicy,
    GuardrailRule,
    GuardrailRuleMatcher,
)
from app.modules.policy_kernel.models import PolicyAssignment, PolicyRevision


@dataclass(frozen=True)
class GuardrailAssignmentView:
    id: UUID
    org_id: UUID
    policy_id: UUID
    shared_policy_id: UUID
    policy_name: str
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    enforcement_mode: str
    is_active: bool
    effective_from: datetime | None
    effective_to: datetime | None
    superseded_by_assignment_id: UUID | None
    created_at: datetime
    updated_at: datetime


async def list_policies(*, org_id: UUID, db: AsyncSession) -> list[GuardrailPolicy]:
    result = await db.scalars(
        select(GuardrailPolicy)
        .where(GuardrailPolicy.org_id == org_id)
        .order_by(GuardrailPolicy.created_at.desc())
    )
    return list(result)


async def get_policy(*, policy_id: UUID, org_id: UUID, db: AsyncSession) -> GuardrailPolicy | None:
    return await db.scalar(
        select(GuardrailPolicy).where(
            GuardrailPolicy.id == policy_id,
            GuardrailPolicy.org_id == org_id,
        )
    )


async def create_policy(
    *,
    org_id: UUID,
    name: str,
    description: str | None,
    enforcement_mode: str,
    is_active: bool,
    db: AsyncSession,
    policy_id: UUID,
) -> GuardrailPolicy:
    policy = GuardrailPolicy(
        policy_id=policy_id,
        org_id=org_id,
        name=name,
        description=description,
        enforcement_mode=enforcement_mode,
        is_active=is_active,
    )
    db.add(policy)
    await db.flush()
    return policy


async def replace_rules(
    *,
    org_id: UUID,
    policy_id: UUID,
    rules: list[dict],
    policy_revision_id: UUID,
    db: AsyncSession,
) -> None:
    await db.execute(
        delete(GuardrailRule).where(
            GuardrailRule.org_id == org_id,
            GuardrailRule.policy_id == policy_id,
            GuardrailRule.policy_revision_id == policy_revision_id,
        )
    )
    for rule in rules:
        matchers = rule.pop("matchers", [])
        guardrail_rule = GuardrailRule(
            org_id=org_id,
            policy_id=policy_id,
            policy_revision_id=policy_revision_id,
            **rule,
        )
        db.add(guardrail_rule)
        await db.flush()
        for matcher in matchers:
            db.add(GuardrailRuleMatcher(org_id=org_id, rule_id=guardrail_rule.id, **matcher))
    await db.flush()


async def list_policy_rules(
    *,
    org_id: UUID,
    policy_ids: list[UUID],
    db: AsyncSession,
) -> list[GuardrailRule]:
    if not policy_ids:
        return []
    active_revisions = await db.execute(
        select(GuardrailPolicy.id, PolicyRevision.id)
        .join(PolicyRevision, PolicyRevision.policy_id == GuardrailPolicy.policy_id)
        .where(
            GuardrailPolicy.org_id == org_id,
            GuardrailPolicy.id.in_(policy_ids),
            PolicyRevision.org_id == org_id,
            PolicyRevision.status == "active",
        )
    )
    active_revision_by_policy = {
        guardrail_policy_id: revision_id
        for guardrail_policy_id, revision_id in active_revisions.all()
    }
    revision_ids = list(active_revision_by_policy.values())
    if not revision_ids:
        return []
    result = await db.scalars(
        select(GuardrailRule)
        .where(
            GuardrailRule.org_id == org_id,
            GuardrailRule.policy_revision_id.in_(revision_ids),
        )
        .order_by(GuardrailRule.priority, GuardrailRule.created_at)
    )
    return list(result)


async def list_rule_matchers(
    *,
    org_id: UUID,
    rule_id: UUID,
    db: AsyncSession,
) -> list[GuardrailRuleMatcher]:
    result = await db.scalars(
        select(GuardrailRuleMatcher)
        .where(
            GuardrailRuleMatcher.org_id == org_id,
            GuardrailRuleMatcher.rule_id == rule_id,
        )
        .order_by(GuardrailRuleMatcher.created_at.asc(), GuardrailRuleMatcher.id.asc())
    )
    return list(result)


def _assignment_view(
    *, assignment: PolicyAssignment, policy: GuardrailPolicy
) -> GuardrailAssignmentView:
    if assignment.policy_id is None:
        raise ValueError("guardrail assignment requires shared policy id")
    return GuardrailAssignmentView(
        id=assignment.id,
        org_id=assignment.org_id,
        policy_id=policy.id,
        shared_policy_id=assignment.policy_id,
        policy_name=policy.name,
        scope_type=assignment.scope_type,
        team_id=assignment.team_id,
        project_id=assignment.project_id,
        virtual_key_id=assignment.virtual_key_id,
        enforcement_mode=assignment.mode,
        is_active=assignment.is_active,
        effective_from=assignment.effective_from,
        effective_to=assignment.effective_to,
        superseded_by_assignment_id=assignment.superseded_by_assignment_id,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


async def list_assignments(*, org_id: UUID, db: AsyncSession) -> list[GuardrailAssignmentView]:
    rows = await db.execute(
        select(PolicyAssignment, GuardrailPolicy)
        .join(GuardrailPolicy, GuardrailPolicy.policy_id == PolicyAssignment.policy_id)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == "guardrail",
            GuardrailPolicy.org_id == org_id,
        )
        .order_by(PolicyAssignment.created_at.desc())
    )
    return [_assignment_view(assignment=assignment, policy=policy) for assignment, policy in rows]


async def list_policy_assignments(
    *, org_id: UUID, policy_id: UUID, active_only: bool, db: AsyncSession
) -> list[GuardrailAssignmentView]:
    policy = await get_policy(policy_id=policy_id, org_id=org_id, db=db)
    if policy is None:
        return []
    filters = [
        PolicyAssignment.org_id == org_id,
        PolicyAssignment.policy_id == policy.policy_id,
        PolicyAssignment.policy_type == "guardrail",
    ]
    if active_only:
        now = datetime.now(UTC)
        filters.extend(
            [
                PolicyAssignment.is_active.is_(True),
                or_(
                    PolicyAssignment.effective_from.is_(None),
                    PolicyAssignment.effective_from <= now,
                ),
                or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
            ]
        )
    result = await db.scalars(select(PolicyAssignment).where(*filters))
    return [_assignment_view(assignment=assignment, policy=policy) for assignment in result]


async def get_assignment(
    *,
    assignment_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> GuardrailAssignmentView | None:
    row = (
        await db.execute(
            select(PolicyAssignment, GuardrailPolicy)
            .join(GuardrailPolicy, GuardrailPolicy.policy_id == PolicyAssignment.policy_id)
            .where(
                PolicyAssignment.id == assignment_id,
                PolicyAssignment.org_id == org_id,
                PolicyAssignment.policy_type == "guardrail",
                GuardrailPolicy.org_id == org_id,
            )
        )
    ).first()
    if row is None:
        return None
    assignment, policy = row
    return _assignment_view(assignment=assignment, policy=policy)


async def find_assignment_for_scope(
    *,
    org_id: UUID,
    policy_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> GuardrailAssignmentView | None:
    policy = await get_policy(policy_id=policy_id, org_id=org_id, db=db)
    if policy is None:
        return None
    row = await db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_id == policy.policy_id,
            PolicyAssignment.policy_type == "guardrail",
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
            PolicyAssignment.effective_to.is_(None),
        )
    )
    return None if row is None else _assignment_view(assignment=row, policy=policy)


async def list_effective_assignments(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    db: AsyncSession,
) -> list[GuardrailAssignmentView]:
    now = datetime.now(UTC)
    rows = await db.execute(
        select(PolicyAssignment, GuardrailPolicy)
        .join(GuardrailPolicy, GuardrailPolicy.policy_id == PolicyAssignment.policy_id)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == "guardrail",
            PolicyAssignment.is_active.is_(True),
            or_(PolicyAssignment.effective_from.is_(None), PolicyAssignment.effective_from <= now),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
            GuardrailPolicy.org_id == org_id,
            or_(
                PolicyAssignment.scope_type == "org",
                and_(PolicyAssignment.scope_type == "team", PolicyAssignment.team_id == team_id),
                and_(
                    PolicyAssignment.scope_type == "project",
                    PolicyAssignment.project_id == project_id,
                ),
                and_(
                    PolicyAssignment.scope_type == "virtual_key",
                    PolicyAssignment.virtual_key_id == virtual_key_id,
                ),
            ),
        )
    )
    return [_assignment_view(assignment=assignment, policy=policy) for assignment, policy in rows]


async def create_event(
    *,
    org_id: UUID,
    policy_id: UUID | None,
    policy_revision_id: UUID | None,
    rule_id: UUID | None,
    decision: str,
    phase: str,
    reason: str,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    provider_id: UUID,
    pool_id: UUID,
    request_id: str | None,
    requested_model: str,
    provider_model: str,
    metadata: dict,
    db: AsyncSession,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
) -> GuardrailEvent:
    event = GuardrailEvent(
        org_id=org_id,
        policy_id=policy_id,
        policy_revision_id=policy_revision_id,
        rule_id=rule_id,
        decision=decision,
        phase=phase,
        reason=reason,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        pool_id=pool_id,
        request_id=request_id or current_request_id(),
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        requested_model=requested_model,
        provider_model=provider_model,
        metadata_=metadata,
    )
    db.add(event)
    await db.flush()
    return event


async def list_events(
    *,
    org_id: UUID,
    decision: str | None,
    phase: str | None,
    policy_id: UUID | None,
    rule_id: UUID | None,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    provider_id: UUID | None,
    pool_id: UUID | None,
    model: str | None,
    limit: int,
    db: AsyncSession,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
) -> list[GuardrailEvent]:
    filters = [GuardrailEvent.org_id == org_id]
    if allowed_team_ids is not None or allowed_project_ids is not None:
        scope_filters = []
        if allowed_team_ids:
            scope_filters.append(GuardrailEvent.team_id.in_(allowed_team_ids))
        if allowed_project_ids:
            scope_filters.append(GuardrailEvent.project_id.in_(allowed_project_ids))
        if not scope_filters:
            return []
        filters.append(or_(*scope_filters))
    if decision is not None:
        filters.append(GuardrailEvent.decision == decision)
    if phase is not None:
        filters.append(GuardrailEvent.phase == phase)
    if policy_id is not None:
        filters.append(GuardrailEvent.policy_id == policy_id)
    if rule_id is not None:
        filters.append(GuardrailEvent.rule_id == rule_id)
    if team_id is not None:
        filters.append(GuardrailEvent.team_id == team_id)
    if project_id is not None:
        filters.append(GuardrailEvent.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(GuardrailEvent.virtual_key_id == virtual_key_id)
    if provider_id is not None:
        filters.append(GuardrailEvent.provider_id == provider_id)
    if pool_id is not None:
        filters.append(GuardrailEvent.pool_id == pool_id)
    if model:
        model_filter = f"%{model.strip()}%"
        filters.append(
            or_(
                GuardrailEvent.requested_model.ilike(model_filter),
                GuardrailEvent.provider_model.ilike(model_filter),
            )
        )
    result = await db.scalars(
        select(GuardrailEvent)
        .where(*filters)
        .order_by(GuardrailEvent.created_at.desc())
        .limit(limit)
    )
    return list(result)


async def list_events_for_gateway_request(
    *,
    org_id: UUID,
    gateway_request_id: UUID,
    db: AsyncSession,
) -> list[GuardrailEvent]:
    result = await db.scalars(
        select(GuardrailEvent)
        .where(
            GuardrailEvent.org_id == org_id,
            GuardrailEvent.gateway_request_id == gateway_request_id,
        )
        .order_by(GuardrailEvent.created_at)
    )
    return list(result)
