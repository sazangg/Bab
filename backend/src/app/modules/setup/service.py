import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.models import Organization, User
from app.modules.setup.schemas import CreateFirstAdminRequest, CreateFirstAdminResponse


class SetupAlreadyCompletedError(RuntimeError):
    pass


async def setup_required(db: AsyncSession) -> bool:
    first_user_id = await db.scalar(select(User.id).limit(1))
    return first_user_id is None


async def create_first_admin(
    payload: CreateFirstAdminRequest,
    db: AsyncSession,
) -> CreateFirstAdminResponse:
    if not await setup_required(db):
        raise SetupAlreadyCompletedError

    org = Organization(
        name=payload.organization_name,
        slug=_slugify(payload.organization_name),
    )
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="super_admin",
    )
    db.add(user)
    await db.commit()

    return CreateFirstAdminResponse(
        email=user.email,
        organization_name=org.name,
        role=user.role,
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"
