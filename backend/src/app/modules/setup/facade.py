from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.setup.internal import service
from app.modules.setup.schemas import CreateFirstAdminRequest, CreateFirstAdminResponse


async def setup_required(db: AsyncSession) -> bool:
    return await service.setup_required(db)


async def create_first_admin(
    payload: CreateFirstAdminRequest,
    db: AsyncSession,
) -> CreateFirstAdminResponse:
    return await service.create_first_admin(payload, db)
