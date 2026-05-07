from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Organization, User
from app.modules.setup.internal.models import SetupLock


async def user_exists(db: AsyncSession) -> bool:
    first_user_id = await db.scalar(select(User.id).limit(1))
    return first_user_id is not None


async def create_setup_lock(db: AsyncSession) -> None:
    db.add(SetupLock())
    await db.flush()


async def create_organization(*, name: str, slug: str, db: AsyncSession) -> Organization:
    org = Organization(name=name, slug=slug)
    db.add(org)
    await db.flush()
    return org


async def create_user(
    *,
    org_id,
    email: str,
    password_hash: str,
    role: str,
    db: AsyncSession,
) -> User:
    user = User(
        org_id=org_id,
        email=email,
        password_hash=password_hash,
        role=role,
    )
    db.add(user)
    await db.flush()
    return user
