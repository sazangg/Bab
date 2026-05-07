import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transaction
from app.core.security import hash_password
from app.modules.setup import repository
from app.modules.setup.errors import SetupAlreadyCompletedError
from app.modules.setup.schemas import CreateFirstAdminRequest, CreateFirstAdminResponse


async def setup_required(db: AsyncSession) -> bool:
    return not await repository.user_exists(db)


async def create_first_admin(
    payload: CreateFirstAdminRequest,
    db: AsyncSession,
) -> CreateFirstAdminResponse:
    try:
        async with transaction(db):
            if not await setup_required(db):
                raise SetupAlreadyCompletedError

            await repository.create_setup_lock(db)
            org = await repository.create_organization(
                name=payload.organization_name,
                slug=_slugify(payload.organization_name),
                db=db,
            )
            user = await repository.create_user(
                org_id=org.id,
                email=payload.email,
                password_hash=hash_password(payload.password),
                role="super_admin",
                db=db,
            )
    except IntegrityError as exc:
        raise SetupAlreadyCompletedError from exc

    return CreateFirstAdminResponse(
        email=user.email,
        organization_name=org.name,
        role=user.role,
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"
