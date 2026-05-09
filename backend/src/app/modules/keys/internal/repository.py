from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import (
    ModelAlias,
    Project,
    ProjectProviderAccess,
    VirtualKey,
    VirtualKeyRequestCounter,
)


async def create_project(
    *,
    org_id: UUID,
    created_by: UUID,
    name: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    project = Project(org_id=org_id, created_by=created_by, name=name, description=description)
    db.add(project)
    await db.flush()
    return project


async def list_projects(*, org_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.org_id == org_id).order_by(Project.name)
    )
    return list(result)


async def get_project(*, project_id: UUID, org_id: UUID, db: AsyncSession) -> Project | None:
    return await db.scalar(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )


async def grant_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    allowed_models: list[str] | None,
    db: AsyncSession,
) -> ProjectProviderAccess:
    access = ProjectProviderAccess(
        org_id=org_id,
        project_id=project_id,
        provider_id=provider_id,
        allowed_models=allowed_models,
    )
    db.add(access)
    await db.flush()
    return access


async def list_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[ProjectProviderAccess]:
    result = await db.scalars(
        select(ProjectProviderAccess)
        .where(
            ProjectProviderAccess.org_id == org_id,
            ProjectProviderAccess.project_id == project_id,
        )
        .order_by(ProjectProviderAccess.created_at.desc())
    )
    return list(result)


async def get_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> ProjectProviderAccess | None:
    return await db.scalar(
        select(ProjectProviderAccess).where(
            ProjectProviderAccess.org_id == org_id,
            ProjectProviderAccess.project_id == project_id,
            ProjectProviderAccess.provider_id == provider_id,
        )
    )


async def delete_provider_access(*, access: ProjectProviderAccess, db: AsyncSession) -> None:
    await db.delete(access)
    await db.flush()


async def create_model_alias(
    *,
    org_id: UUID,
    alias: str,
    provider_id: UUID,
    provider_model: str,
    db: AsyncSession,
) -> ModelAlias:
    model_alias = ModelAlias(
        org_id=org_id,
        alias=alias,
        provider_id=provider_id,
        provider_model=provider_model,
    )
    db.add(model_alias)
    await db.flush()
    return model_alias


async def list_model_aliases(*, org_id: UUID, db: AsyncSession) -> list[ModelAlias]:
    result = await db.scalars(
        select(ModelAlias).where(ModelAlias.org_id == org_id).order_by(ModelAlias.alias)
    )
    return list(result)


async def get_model_alias(*, alias_id: UUID, org_id: UUID, db: AsyncSession) -> ModelAlias | None:
    return await db.scalar(
        select(ModelAlias).where(ModelAlias.id == alias_id, ModelAlias.org_id == org_id)
    )


async def get_model_alias_by_name(
    *,
    alias: str,
    org_id: UUID,
    db: AsyncSession,
) -> ModelAlias | None:
    return await db.scalar(
        select(ModelAlias).where(ModelAlias.alias == alias, ModelAlias.org_id == org_id)
    )


async def get_active_model_alias_by_name(
    *,
    alias: str,
    org_id: UUID,
    db: AsyncSession,
) -> ModelAlias | None:
    return await db.scalar(
        select(ModelAlias).where(
            ModelAlias.alias == alias,
            ModelAlias.org_id == org_id,
            ModelAlias.is_active.is_(True),
        )
    )


async def create_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
    name: str,
    key_hash: str,
    key_prefix: str,
    restrictions: list[dict[str, object]] | None,
    request_limit_per_minute: int | None,
    request_limit_per_day: int | None,
    expires_at,
    db: AsyncSession,
) -> VirtualKey:
    virtual_key = VirtualKey(
        org_id=org_id,
        project_id=project_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        restrictions=restrictions,
        request_limit_per_minute=request_limit_per_minute,
        request_limit_per_day=request_limit_per_day,
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


async def get_virtual_key_by_hash(*, key_hash: str, db: AsyncSession) -> VirtualKey | None:
    return await db.scalar(select(VirtualKey).where(VirtualKey.key_hash == key_hash))


async def increment_request_counter_if_below_limit(
    *,
    org_id: UUID,
    virtual_key_id: UUID,
    window_kind: str,
    window_start: datetime,
    limit: int,
    db: AsyncSession,
) -> bool:
    updated = await _increment_existing_counter_if_below_limit(
        virtual_key_id=virtual_key_id,
        window_kind=window_kind,
        window_start=window_start,
        limit=limit,
        db=db,
    )
    if updated:
        return True

    existing = await _get_request_counter(
        virtual_key_id=virtual_key_id,
        window_kind=window_kind,
        window_start=window_start,
        db=db,
    )
    if existing is not None:
        return False

    counter = VirtualKeyRequestCounter(
        org_id=org_id,
        virtual_key_id=virtual_key_id,
        window_kind=window_kind,
        window_start=window_start,
        request_count=1,
    )
    try:
        async with db.begin_nested():
            db.add(counter)
            await db.flush()
        return True
    except IntegrityError:
        return await _increment_existing_counter_if_below_limit(
            virtual_key_id=virtual_key_id,
            window_kind=window_kind,
            window_start=window_start,
            limit=limit,
            db=db,
        )


async def _increment_existing_counter_if_below_limit(
    *,
    virtual_key_id: UUID,
    window_kind: str,
    window_start: datetime,
    limit: int,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        update(VirtualKeyRequestCounter)
        .where(
            VirtualKeyRequestCounter.virtual_key_id == virtual_key_id,
            VirtualKeyRequestCounter.window_kind == window_kind,
            VirtualKeyRequestCounter.window_start == window_start,
            VirtualKeyRequestCounter.request_count < limit,
        )
        .values(request_count=VirtualKeyRequestCounter.request_count + 1)
    )
    return result.rowcount == 1


async def _get_request_counter(
    *,
    virtual_key_id: UUID,
    window_kind: str,
    window_start: datetime,
    db: AsyncSession,
) -> VirtualKeyRequestCounter | None:
    return await db.scalar(
        select(VirtualKeyRequestCounter).where(
            VirtualKeyRequestCounter.virtual_key_id == virtual_key_id,
            VirtualKeyRequestCounter.window_kind == window_kind,
            VirtualKeyRequestCounter.window_start == window_start,
        )
    )
