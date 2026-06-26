from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import VirtualKey
from app.modules.workspace.internal.models import Project


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
