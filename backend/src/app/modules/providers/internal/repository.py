from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal.models import Provider


async def create_provider(
    *,
    org_id: UUID,
    name: str,
    base_url: str,
    api_key_encrypted: str,
    adapter_type: str,
    db: AsyncSession,
) -> Provider:
    provider = Provider(
        org_id=org_id,
        name=name,
        base_url=base_url,
        api_key_encrypted=api_key_encrypted,
        adapter_type=adapter_type,
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(*, org_id: UUID, db: AsyncSession) -> list[Provider]:
    result = await db.scalars(
        select(Provider).where(Provider.org_id == org_id).order_by(Provider.created_at.desc())
    )
    return list(result)


async def get_provider(*, provider_id: UUID, org_id: UUID, db: AsyncSession) -> Provider | None:
    return await db.scalar(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
