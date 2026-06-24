from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policy_kernel.models import Policy, PolicyAssignment, PolicyRevision


async def create_policy(
    *,
    org_id: UUID,
    kind: str,
    name: str,
    description: str | None,
    is_active: bool,
    db: AsyncSession,
) -> Policy:
    policy = Policy(
        org_id=org_id,
        kind=kind,
        name=name,
        description=description,
        is_active=is_active,
    )
    db.add(policy)
    await db.flush()
    return policy


async def get_policy(*, org_id: UUID, policy_id: UUID, db: AsyncSession) -> Policy | None:
    return await db.scalar(
        select(Policy).where(
            Policy.org_id == org_id,
            Policy.id == policy_id,
        )
    )


async def create_policy_revision(
    *,
    org_id: UUID,
    policy_id: UUID,
    revision_number: int,
    status: str,
    created_by: UUID | None,
    db: AsyncSession,
) -> PolicyRevision:
    revision = PolicyRevision(
        org_id=org_id,
        policy_id=policy_id,
        revision_number=revision_number,
        status=status,
        created_by=created_by,
    )
    db.add(revision)
    await db.flush()
    return revision


async def get_active_policy_revision(
    *,
    org_id: UUID,
    policy_id: UUID,
    db: AsyncSession,
) -> PolicyRevision | None:
    return await db.scalar(
        select(PolicyRevision).where(
            PolicyRevision.org_id == org_id,
            PolicyRevision.policy_id == policy_id,
            PolicyRevision.status == "active",
        )
    )


async def get_latest_policy_revision(
    *, org_id: UUID, policy_id: UUID, db: AsyncSession
) -> PolicyRevision | None:
    return await db.scalar(
        select(PolicyRevision)
        .where(PolicyRevision.org_id == org_id, PolicyRevision.policy_id == policy_id)
        .order_by(PolicyRevision.revision_number.desc())
        .limit(1)
    )


async def archive_active_policy_revision(
    *,
    org_id: UUID,
    policy_id: UUID,
    db: AsyncSession,
) -> PolicyRevision | None:
    revision = await get_active_policy_revision(org_id=org_id, policy_id=policy_id, db=db)
    if revision is None:
        return None
    revision.status = "archived"
    revision.archived_at = datetime.now(UTC)
    await db.flush()
    return revision


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


async def get_policy_assignment(
    *, assignment_id: UUID, org_id: UUID, db: AsyncSession
) -> PolicyAssignment | None:
    return await db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.id == assignment_id,
            PolicyAssignment.org_id == org_id,
        )
    )


async def list_policy_assignments(*, org_id: UUID, db: AsyncSession) -> list[PolicyAssignment]:
    result = await db.scalars(
        select(PolicyAssignment)
        .where(PolicyAssignment.org_id == org_id)
        .order_by(PolicyAssignment.created_at.desc())
    )
    return list(result)


async def list_policy_assignments_for_policy(
    *, org_id: UUID, policy_id: UUID, active_only: bool, db: AsyncSession
) -> list[PolicyAssignment]:
    filters = [
        PolicyAssignment.org_id == org_id,
        PolicyAssignment.policy_id == policy_id,
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
    return list(result)


async def close_assignments_for_policy(
    *, org_id: UUID, policy_id: UUID, closed_at: datetime, db: AsyncSession
) -> None:
    await db.execute(
        update(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_id == policy_id,
            PolicyAssignment.is_active.is_(True),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > closed_at),
        )
        .values(is_active=False, effective_to=closed_at)
    )


async def find_active_policy_assignment_for_scope(
    *,
    org_id: UUID,
    policy_id: UUID,
    policy_type: str,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> PolicyAssignment | None:
    now = datetime.now(UTC)
    return await db.scalar(
        select(PolicyAssignment).where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_id == policy_id,
            PolicyAssignment.policy_type == policy_type,
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
            or_(PolicyAssignment.effective_from.is_(None), PolicyAssignment.effective_from <= now),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
        )
    )


async def list_active_policy_assignments_for_scope(
    *,
    org_id: UUID,
    scope_type: str,
    policy_type: str,
    db: AsyncSession,
) -> list[PolicyAssignment]:
    now = datetime.now(UTC)
    result = await db.scalars(
        select(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.scope_type == scope_type,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.is_active.is_(True),
            or_(PolicyAssignment.effective_from.is_(None), PolicyAssignment.effective_from <= now),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
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
    now = datetime.now(UTC)
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
    result = await db.scalars(
        select(PolicyAssignment)
        .where(
            PolicyAssignment.org_id == org_id,
            PolicyAssignment.policy_type == policy_type,
            PolicyAssignment.is_active.is_(True),
            or_(PolicyAssignment.effective_from.is_(None), PolicyAssignment.effective_from <= now),
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to > now),
            or_(*target_filters),
        )
        .order_by(PolicyAssignment.created_at)
    )
    return list(result)
