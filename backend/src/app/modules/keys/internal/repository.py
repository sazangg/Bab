from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import VirtualKey


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
) -> list[tuple[UUID, str, UUID]]:
    if not project_ids:
        return []
    filters = [
        VirtualKey.org_id == org_id,
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
            select(VirtualKey.id, VirtualKey.name, VirtualKey.project_id)
            .where(*filters)
            .order_by(VirtualKey.name)
        )
    ).all()
    return list(rows)


async def list_virtual_key_options_by_ids(
    *, org_id: UUID, virtual_key_ids: set[UUID], usable_only: bool, db: AsyncSession
) -> list[tuple[UUID, str, UUID]]:
    if not virtual_key_ids:
        return []
    filters = [
        VirtualKey.org_id == org_id,
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
            select(VirtualKey.id, VirtualKey.name, VirtualKey.project_id)
            .where(*filters)
            .order_by(VirtualKey.name)
        )
    ).all()
    return list(rows)


async def get_usable_virtual_key_target(
    *, org_id: UUID, virtual_key_id: UUID, db: AsyncSession
) -> VirtualKey | None:
    return await db.scalar(
        select(VirtualKey).where(
            VirtualKey.org_id == org_id,
            VirtualKey.id == virtual_key_id,
            VirtualKey.revoked_at.is_(None),
            or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
        )
    )


async def count_active_virtual_keys_for_project_ids(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> int:
    if not project_ids:
        return 0
    count = await db.scalar(
        select(func.count(VirtualKey.id)).where(
            VirtualKey.org_id == org_id,
            VirtualKey.project_id.in_(project_ids),
            VirtualKey.revoked_at.is_(None),
            or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > func.now()),
        )
    )
    return int(count or 0)

async def list_virtual_key_inventory(
    *,
    org_id: UUID,
    project_ids: set[UUID] | None,
    status: str | None,
    search: str | None,
    usage: str | None,
    limit: int | None,
    offset: int,
    include_total: bool = True,
    db: AsyncSession,
) -> tuple[list[VirtualKey], int]:
    filters = [
        VirtualKey.org_id == org_id,
    ]
    if project_ids is not None:
        if not project_ids:
            return [], 0
        filters.append(VirtualKey.project_id.in_(project_ids))
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
            ]
        )
    elif status == "team_archived":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
            ]
        )
    elif status == "expiring_soon":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                VirtualKey.expires_at.is_not(None),
                VirtualKey.expires_at > now,
                VirtualKey.expires_at <= now + timedelta(days=7),
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
            ]
        )
    elif status == "no_effective_access":
        filters.extend(
            [
                VirtualKey.revoked_at.is_(None),
                or_(VirtualKey.expires_at.is_(None), VirtualKey.expires_at > now),
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
            ]
        )

    total = (
        await db.scalar(select(func.count(VirtualKey.id)).where(and_(*filters)))
        if include_total
        else 0
    )
    query = (
        select(VirtualKey)
        .where(and_(*filters))
        .order_by(VirtualKey.created_at.desc(), VirtualKey.id.desc())
    )
    if limit is not None:
        query = query.limit(limit).offset(offset)
    rows = await db.scalars(query)
    return list(rows), int(total or 0)
