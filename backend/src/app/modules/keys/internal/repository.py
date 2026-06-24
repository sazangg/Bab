from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import (
    Organization,
    ProjectMembership,
    TeamMembership,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.usage.internal.models import UsageRecord
from app.modules.workspace.internal.models import Project


async def get_organization(*, org_id: UUID, db: AsyncSession) -> Organization | None:
    return await db.scalar(select(Organization).where(Organization.id == org_id))


async def create_project(
    *,
    org_id: UUID,
    team_id: UUID,
    created_by: UUID,
    name: str,
    slug: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    project = Project(
        org_id=org_id,
        team_id=team_id,
        created_by=created_by,
        name=name,
        slug=slug,
        description=description,
    )
    db.add(project)
    await db.flush()
    return project


async def list_projects(*, org_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.org_id == org_id).order_by(Project.name)
    )
    return list(result)


async def list_team_projects(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project)
        .where(Project.org_id == org_id, Project.team_id == team_id)
        .order_by(Project.name)
    )
    return list(result)


async def get_project(*, project_id: UUID, org_id: UUID, db: AsyncSession) -> Project | None:
    return await db.scalar(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )


async def get_project_by_slug(
    *, org_id: UUID, team_id: UUID, slug: str, db: AsyncSession
) -> Project | None:
    return await db.scalar(
        select(Project).where(
            Project.org_id == org_id,
            Project.team_id == team_id,
            Project.slug == slug,
        )
    )


async def create_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
    name: str,
    key_hash: str,
    key_prefix: str,
    created_by: UUID,
    expires_at,
    db: AsyncSession,
    supersedes_key_id: UUID | None = None,
) -> VirtualKey:
    virtual_key = VirtualKey(
        org_id=org_id,
        project_id=project_id,
        supersedes_key_id=supersedes_key_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=created_by,
        expires_at=expires_at,
    )
    db.add(virtual_key)
    await db.flush()
    return virtual_key


async def list_virtual_keys(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[VirtualKey]:
    result = await db.scalars(
        select(VirtualKey)
        .where(VirtualKey.org_id == org_id, VirtualKey.project_id == project_id)
        .order_by(VirtualKey.created_at.desc())
    )
    return list(result)


async def get_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
    key_id: UUID,
    db: AsyncSession,
) -> VirtualKey | None:
    return await db.scalar(
        select(VirtualKey).where(
            VirtualKey.org_id == org_id,
            VirtualKey.project_id == project_id,
            VirtualKey.id == key_id,
        )
    )


async def get_virtual_key_by_id(
    *,
    org_id: UUID,
    key_id: UUID,
    db: AsyncSession,
) -> VirtualKey | None:
    return await db.scalar(
        select(VirtualKey).where(VirtualKey.org_id == org_id, VirtualKey.id == key_id)
    )


async def get_virtual_key_by_hash(*, key_hash: str, db: AsyncSession) -> VirtualKey | None:
    return await db.scalar(select(VirtualKey).where(VirtualKey.key_hash == key_hash))


async def get_project_labels(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> dict[UUID, str]:
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(Project.id, Project.name).where(
                Project.org_id == org_id,
                Project.id.in_(project_ids),
            )
        )
    ).all()
    return {project_id: name for project_id, name in rows}


async def get_project_membership_target(
    *, org_id: UUID, project_id: UUID, db: AsyncSession
) -> tuple[UUID, UUID, UUID, str, bool] | None:
    return (
        await db.execute(
            select(Project.id, Project.org_id, Project.team_id, Project.name, Project.is_active)
            .where(Project.org_id == org_id, Project.id == project_id)
        )
    ).one_or_none()


async def get_project_team_ids(
    *, org_id: UUID, project_ids: set[UUID] | None, db: AsyncSession
) -> dict[UUID, UUID]:
    if project_ids is not None and not project_ids:
        return {}
    query = select(Project.id, Project.team_id).where(Project.org_id == org_id)
    if project_ids is not None:
        query = query.where(Project.id.in_(project_ids))
    rows = (await db.execute(query)).all()
    return {project_id: team_id for project_id, team_id in rows}


async def get_virtual_key_labels(
    *, org_id: UUID, virtual_key_ids: set[UUID], db: AsyncSession
) -> dict[UUID, str]:
    if not virtual_key_ids:
        return {}
    rows = (
        await db.execute(
            select(VirtualKey.id, VirtualKey.name).where(
                VirtualKey.org_id == org_id,
                VirtualKey.id.in_(virtual_key_ids),
            )
        )
    ).all()
    return {virtual_key_id: name for virtual_key_id, name in rows}


async def list_project_ids_for_team_ids(
    *, org_id: UUID, team_ids: set[UUID], db: AsyncSession
) -> set[UUID]:
    if not team_ids:
        return set()
    result = await db.scalars(
        select(Project.id).where(Project.org_id == org_id, Project.team_id.in_(team_ids))
    )
    return set(result)


async def list_virtual_key_ids_for_project_ids(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> set[UUID]:
    if not project_ids:
        return set()
    result = await db.scalars(
        select(VirtualKey.id).where(
            VirtualKey.org_id == org_id,
            VirtualKey.project_id.in_(project_ids),
        )
    )
    return set(result)


async def list_project_options(
    *,
    org_id: UUID,
    team_ids: set[UUID] | None,
    project_ids: set[UUID] | None,
    db: AsyncSession,
) -> list[tuple[UUID, str, UUID]]:
    filters = [Project.org_id == org_id]
    if team_ids is not None:
        if not team_ids:
            return []
        filters.append(Project.team_id.in_(team_ids))
    if project_ids is not None:
        if not project_ids:
            return []
        filters.append(Project.id.in_(project_ids))
    rows = (
        await db.execute(
            select(Project.id, Project.name, Project.team_id)
            .where(*filters)
            .order_by(Project.name)
        )
    ).all()
    return list(rows)


async def list_virtual_key_options_for_project_ids(
    *, org_id: UUID, project_ids: set[UUID], usable_only: bool, db: AsyncSession
) -> list[tuple[UUID, str, UUID, str]]:
    if not project_ids:
        return []
    filters = [
        VirtualKey.org_id == org_id,
        Project.org_id == org_id,
        VirtualKey.project_id.in_(project_ids),
    ]
    if usable_only:
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
            ]
        )
    rows = (
        await db.execute(
            select(VirtualKey.id, VirtualKey.name, Project.id, Project.name)
            .join(Project, Project.id == VirtualKey.project_id)
            .where(*filters)
            .order_by(Project.name, VirtualKey.name)
        )
    ).all()
    return list(rows)


async def list_virtual_key_options_by_ids(
    *, org_id: UUID, virtual_key_ids: set[UUID], usable_only: bool, db: AsyncSession
) -> list[tuple[UUID, str, UUID, str]]:
    if not virtual_key_ids:
        return []
    filters = [
        VirtualKey.org_id == org_id,
        Project.org_id == org_id,
        VirtualKey.id.in_(virtual_key_ids),
    ]
    if usable_only:
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
            ]
        )
    rows = (
        await db.execute(
            select(VirtualKey.id, VirtualKey.name, Project.id, Project.name)
            .join(Project, Project.id == VirtualKey.project_id)
            .where(*filters)
            .order_by(Project.name, VirtualKey.name)
        )
    ).all()
    return list(rows)


async def get_usable_virtual_key_target(
    *, org_id: UUID, virtual_key_id: UUID, db: AsyncSession
) -> tuple[UUID, UUID, UUID, UUID, str | None] | None:
    row = (
        await db.execute(
            select(
                VirtualKey.org_id,
                Project.team_id,
                Project.id,
                VirtualKey.id,
                VirtualKey.name,
            )
            .join(Project, Project.id == VirtualKey.project_id)
            .where(
                VirtualKey.org_id == org_id,
                Project.org_id == org_id,
                VirtualKey.id == virtual_key_id,
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
                Project.is_active.is_(True),
            )
        )
    ).first()
    return row


async def count_active_team_projects(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count(Project.id)).where(
            Project.org_id == org_id,
            Project.team_id == team_id,
            Project.is_active.is_(True),
        )
    )
    return int(count or 0)


async def count_active_team_virtual_keys(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count(VirtualKey.id))
        .join(Project, Project.id == VirtualKey.project_id)
        .where(
            VirtualKey.org_id == org_id,
            Project.org_id == org_id,
            Project.team_id == team_id,
            Project.is_active.is_(True),
            VirtualKey.revoked_at.is_(None),
            or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
        )
    )
    return int(count or 0)


async def count_active_project_virtual_keys(
    *, org_id: UUID, project_id: UUID, db: AsyncSession
) -> int:
    count = await db.scalar(
        select(func.count(VirtualKey.id))
        .join(Project, Project.id == VirtualKey.project_id)
        .where(
            VirtualKey.org_id == org_id,
            Project.org_id == org_id,
            Project.id == project_id,
            Project.is_active.is_(True),
            VirtualKey.revoked_at.is_(None),
            or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
        )
    )
    return int(count or 0)


async def count_team_members_by_role(
    *,
    org_id: UUID,
    team_id: UUID,
    db: AsyncSession,
) -> tuple[int, int]:
    rows = (
        await db.execute(
            select(TeamMembership.role, func.count(TeamMembership.id))
            .where(TeamMembership.org_id == org_id, TeamMembership.team_id == team_id)
            .group_by(TeamMembership.role)
        )
    ).all()
    counts = {role: int(count) for role, count in rows}
    return counts.get("team_admin", 0), counts.get("team_member", 0)


async def count_project_admins(*, org_id: UUID, project_id: UUID, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count(ProjectMembership.id)).where(
            ProjectMembership.org_id == org_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.role == "project_admin",
        )
    )
    return int(count or 0)


async def summarize_recent_usage(
    *,
    org_id: UUID,
    since,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> tuple[int, int]:
    filters = [UsageRecord.org_id == org_id, UsageRecord.created_at >= since]
    if team_id is not None:
        filters.append(UsageRecord.team_id == team_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    row = (
        await db.execute(
            select(
                func.count(UsageRecord.id),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
            ).where(*filters)
        )
    ).one()
    return int(row[0]), int(row[1])


async def list_virtual_key_inventory(
    *,
    org_id: UUID,
    active_team_ids: set[UUID],
    team_ids: set[UUID] | None,
    project_ids: set[UUID] | None,
    team_id: UUID | None,
    project_id: UUID | None,
    status: str | None,
    search: str | None,
    usage: str | None,
    limit: int | None,
    offset: int,
    include_total: bool = True,
    db: AsyncSession,
) -> tuple[list[tuple[VirtualKey, Project]], int]:
    filters = [
        VirtualKey.org_id == org_id,
        Project.org_id == org_id,
    ]
    if team_ids is not None and project_ids is not None:
        visibility = []
        if team_ids:
            visibility.append(Project.team_id.in_(team_ids))
        if project_ids:
            visibility.append(Project.id.in_(project_ids))
        filters.append(or_(*visibility) if visibility else Project.id.is_(None))
    if team_id is not None:
        filters.append(Project.team_id == team_id)
    if project_id is not None:
        filters.append(Project.id == project_id)
    if search:
        # autoescape escapes %/_ so a literal wildcard in the term matches verbatim.
        term = search.strip()
        filters.append(
            or_(
                VirtualKey.name.icontains(term, autoescape=True),
                VirtualKey.key_prefix.icontains(term, autoescape=True),
            )
        )
    if usage == "used":
        filters.append(VirtualKey.last_used_at.is_not(None))
    elif usage == "never":
        filters.append(VirtualKey.last_used_at.is_(None))

    now = func.now()
    if status == "revoked":
        filters.append(VirtualKey.revoked_at.is_not(None))
    elif status == "expired":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                VirtualKey.expires_at.is_not(None),
                VirtualKey.expires_at <= now,
            ]
        )
    elif status == "project_archived":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
                Project.is_active.is_(False),
            ]
        )
    elif status == "team_archived":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
                Project.is_active.is_(True),
                Project.team_id.not_in(active_team_ids),
            ]
        )
    elif status == "expiring_soon":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                VirtualKey.expires_at.is_not(None),
                VirtualKey.expires_at > now,
                VirtualKey.expires_at <= now + timedelta(days=7),
                Project.is_active.is_(True),
                Project.team_id.in_(active_team_ids),
            ]
        )
    elif status == "unused":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
                or_(
                    VirtualKey.expires_at.is_(None),
                    VirtualKey.expires_at > now + timedelta(days=7),
                ),
                VirtualKey.last_used_at.is_(None),
                Project.is_active.is_(True),
                Project.team_id.in_(active_team_ids),
            ]
        )
    elif status == "no_effective_access":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
                Project.is_active.is_(True),
                Project.team_id.in_(active_team_ids),
            ]
        )
    elif status == "active":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
                or_(
                    VirtualKey.expires_at.is_(None),
                    VirtualKey.expires_at > now + timedelta(days=7),
                ),
                VirtualKey.last_used_at.is_not(None),
                Project.is_active.is_(True),
                Project.team_id.in_(active_team_ids),
            ]
        )

    joins = VirtualKey.__table__.join(Project, Project.id == VirtualKey.project_id)
    total = (
        await db.scalar(select(func.count()).select_from(joins).where(and_(*filters)))
        if include_total
        else 0
    )
    query = (
        select(VirtualKey, Project)
        .select_from(joins)
        .where(and_(*filters))
        .order_by(VirtualKey.created_at.desc(), VirtualKey.id.desc())
    )
    if limit is not None:
        query = query.limit(limit).offset(offset)
    rows = (await db.execute(query)).all()
    return list(rows), int(total or 0)
