from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Team
from app.modules.guardrails.internal.models import (
    GuardrailAssignment,
    GuardrailEvent,
    GuardrailPolicy,
    GuardrailRule,
)
from app.modules.keys.internal.models import Allocation, Project, VirtualKey


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
) -> GuardrailPolicy:
    policy = GuardrailPolicy(
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
    db: AsyncSession,
) -> None:
    await db.execute(delete(GuardrailRule).where(GuardrailRule.policy_id == policy_id))
    for rule in rules:
        db.add(GuardrailRule(org_id=org_id, policy_id=policy_id, **rule))
    await db.flush()


async def delete_policy(*, policy: GuardrailPolicy, db: AsyncSession) -> None:
    await db.delete(policy)
    await db.flush()


async def list_policy_rules(
    *,
    org_id: UUID,
    policy_ids: list[UUID],
    db: AsyncSession,
) -> list[GuardrailRule]:
    if not policy_ids:
        return []
    result = await db.scalars(
        select(GuardrailRule)
        .where(
            GuardrailRule.org_id == org_id,
            GuardrailRule.policy_id.in_(policy_ids),
        )
        .order_by(GuardrailRule.priority, GuardrailRule.created_at)
    )
    return list(result)


async def list_assignments(*, org_id: UUID, db: AsyncSession) -> list[GuardrailAssignment]:
    result = await db.scalars(
        select(GuardrailAssignment)
        .where(GuardrailAssignment.org_id == org_id)
        .order_by(GuardrailAssignment.created_at.desc())
    )
    return list(result)


async def get_assignment(
    *,
    assignment_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> GuardrailAssignment | None:
    return await db.scalar(
        select(GuardrailAssignment).where(
            GuardrailAssignment.id == assignment_id,
            GuardrailAssignment.org_id == org_id,
        )
    )


async def create_assignment(
    *,
    org_id: UUID,
    policy_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    is_active: bool,
    db: AsyncSession,
) -> GuardrailAssignment:
    assignment = GuardrailAssignment(
        org_id=org_id,
        policy_id=policy_id,
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        allocation_id=allocation_id,
        virtual_key_id=virtual_key_id,
        is_active=is_active,
    )
    db.add(assignment)
    await db.flush()
    return assignment


async def find_assignment_for_scope(
    *,
    org_id: UUID,
    policy_id: UUID,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> GuardrailAssignment | None:
    return await db.scalar(
        select(GuardrailAssignment).where(
            GuardrailAssignment.org_id == org_id,
            GuardrailAssignment.policy_id == policy_id,
            GuardrailAssignment.scope_type == scope_type,
            GuardrailAssignment.team_id.is_(None)
            if team_id is None
            else GuardrailAssignment.team_id == team_id,
            GuardrailAssignment.project_id.is_(None)
            if project_id is None
            else GuardrailAssignment.project_id == project_id,
            GuardrailAssignment.allocation_id.is_(None)
            if allocation_id is None
            else GuardrailAssignment.allocation_id == allocation_id,
            GuardrailAssignment.virtual_key_id.is_(None)
            if virtual_key_id is None
            else GuardrailAssignment.virtual_key_id == virtual_key_id,
        )
    )


async def assignment_target_exists(
    *,
    org_id: UUID,
    scope_type: str,
    target_id: UUID | None,
    db: AsyncSession,
) -> bool:
    if scope_type == "org":
        return True
    if target_id is None:
        return False
    model = {
        "team": Team,
        "project": Project,
        "allocation": Allocation,
        "virtual_key": VirtualKey,
    }.get(scope_type)
    if model is None:
        return False
    exists = await db.scalar(select(model.id).where(model.org_id == org_id, model.id == target_id))
    return exists is not None


async def delete_assignment(*, assignment: GuardrailAssignment, db: AsyncSession) -> None:
    await db.delete(assignment)
    await db.flush()


async def list_effective_assignments(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    allocation_ids: list[UUID],
    virtual_key_id: UUID,
    db: AsyncSession,
) -> list[GuardrailAssignment]:
    result = await db.scalars(
        select(GuardrailAssignment).where(
            GuardrailAssignment.org_id == org_id,
            GuardrailAssignment.is_active.is_(True),
            or_(
                GuardrailAssignment.scope_type == "org",
                GuardrailAssignment.team_id == team_id,
                GuardrailAssignment.project_id == project_id,
                GuardrailAssignment.allocation_id.in_(allocation_ids),
                GuardrailAssignment.virtual_key_id == virtual_key_id,
            ),
        )
    )
    return list(result)


async def create_event(
    *,
    org_id: UUID,
    policy_id: UUID | None,
    rule_id: UUID | None,
    decision: str,
    reason: str,
    team_id: UUID,
    project_id: UUID,
    allocation_id: UUID,
    virtual_key_id: UUID,
    provider_id: UUID,
    pool_id: UUID,
    requested_model: str,
    provider_model: str,
    metadata: dict,
    db: AsyncSession,
) -> GuardrailEvent:
    event = GuardrailEvent(
        org_id=org_id,
        policy_id=policy_id,
        rule_id=rule_id,
        decision=decision,
        reason=reason,
        team_id=team_id,
        project_id=project_id,
        allocation_id=allocation_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        pool_id=pool_id,
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
    policy_id: UUID | None,
    rule_id: UUID | None,
    team_id: UUID | None,
    project_id: UUID | None,
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    provider_id: UUID | None,
    pool_id: UUID | None,
    model: str | None,
    limit: int,
    db: AsyncSession,
) -> list[GuardrailEvent]:
    filters = [GuardrailEvent.org_id == org_id]
    if decision is not None:
        filters.append(GuardrailEvent.decision == decision)
    if policy_id is not None:
        filters.append(GuardrailEvent.policy_id == policy_id)
    if rule_id is not None:
        filters.append(GuardrailEvent.rule_id == rule_id)
    if team_id is not None:
        filters.append(GuardrailEvent.team_id == team_id)
    if project_id is not None:
        filters.append(GuardrailEvent.project_id == project_id)
    if allocation_id is not None:
        filters.append(GuardrailEvent.allocation_id == allocation_id)
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
