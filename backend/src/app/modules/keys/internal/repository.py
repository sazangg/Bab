from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import (
    ModelAlias,
    Project,
    ProjectProviderAccess,
    ProjectSubscriptionAccess,
    Subscription,
    SubscriptionProviderKey,
    VirtualKey,
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


async def create_subscription(
    *,
    org_id: UUID,
    name: str,
    description: str | None,
    db: AsyncSession,
) -> Subscription:
    subscription = Subscription(org_id=org_id, name=name, description=description)
    db.add(subscription)
    await db.flush()
    return subscription


async def get_subscription(
    *,
    org_id: UUID,
    subscription_id: UUID,
    db: AsyncSession,
) -> Subscription | None:
    return await db.scalar(
        select(Subscription).where(
            Subscription.org_id == org_id,
            Subscription.id == subscription_id,
        )
    )


async def list_subscriptions(*, org_id: UUID, db: AsyncSession) -> list[Subscription]:
    result = await db.scalars(
        select(Subscription).where(Subscription.org_id == org_id).order_by(Subscription.name)
    )
    return list(result)


async def attach_provider_key_to_subscription(
    *,
    org_id: UUID,
    subscription_id: UUID,
    provider_key_id: UUID,
    priority: int,
    db: AsyncSession,
) -> SubscriptionProviderKey:
    attachment = SubscriptionProviderKey(
        org_id=org_id,
        subscription_id=subscription_id,
        provider_key_id=provider_key_id,
        priority=priority,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def list_subscription_provider_keys(
    *,
    org_id: UUID,
    subscription_id: UUID,
    db: AsyncSession,
) -> list[SubscriptionProviderKey]:
    result = await db.scalars(
        select(SubscriptionProviderKey)
        .where(
            SubscriptionProviderKey.org_id == org_id,
            SubscriptionProviderKey.subscription_id == subscription_id,
        )
        .order_by(SubscriptionProviderKey.priority.asc(), SubscriptionProviderKey.created_at.asc())
    )
    return list(result)


async def grant_project_subscription_access(
    *,
    org_id: UUID,
    project_id: UUID,
    subscription_id: UUID,
    priority: int,
    db: AsyncSession,
) -> ProjectSubscriptionAccess:
    access = ProjectSubscriptionAccess(
        org_id=org_id,
        project_id=project_id,
        subscription_id=subscription_id,
        priority=priority,
    )
    db.add(access)
    await db.flush()
    return access


async def list_project_subscription_access(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[ProjectSubscriptionAccess]:
    result = await db.scalars(
        select(ProjectSubscriptionAccess)
        .where(
            ProjectSubscriptionAccess.org_id == org_id,
            ProjectSubscriptionAccess.project_id == project_id,
        )
        .order_by(ProjectSubscriptionAccess.priority.asc(), ProjectSubscriptionAccess.created_at)
    )
    return list(result)


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
