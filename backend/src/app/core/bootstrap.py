import re

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine, transaction
from app.core.security import hash_password
from app.modules.audit.internal.models import AuditLog  # noqa: F401
from app.modules.auth.internal.models import Organization, RefreshToken, Team, User  # noqa: F401
from app.modules.keys.internal.models import (  # noqa: F401
    ModelAlias,
    Project,
    ProjectProviderAccess,
    VirtualKey,
)
from app.modules.limits.internal.models import LimitCounter, LimitPolicy  # noqa: F401
from app.modules.providers.internal.models import Provider  # noqa: F401
from app.modules.request_logs.internal.models import RequestLog  # noqa: F401
from app.modules.setup.internal.models import SetupLock  # noqa: F401


async def create_development_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            existing_columns = await connection.exec_driver_sql("PRAGMA table_info(users)")
            user_column_names = {row[1] for row in existing_columns}
            if "team_id" not in user_column_names:
                await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN team_id CHAR(32)")

            existing_columns = await connection.exec_driver_sql("PRAGMA table_info(provider_keys)")
            column_names = {row[1] for row in existing_columns}
            if "created_by" not in column_names:
                await connection.exec_driver_sql(
                    "ALTER TABLE provider_keys ADD COLUMN created_by CHAR(32)"
                )
            if "last_used_at" not in column_names:
                await connection.exec_driver_sql(
                    "ALTER TABLE provider_keys ADD COLUMN last_used_at DATETIME"
                )


async def ensure_default_workspace() -> None:
    async with AsyncSessionLocal() as db:
        await sync_default_workspace(db)


async def sync_default_workspace(db) -> None:
    async with transaction(db):
        org_slug = _slugify(settings.default_organization_name)
        org = await db.scalar(select(Organization).where(Organization.slug == org_slug))
        if org is None:
            org = Organization(name=settings.default_organization_name, slug=org_slug)
            db.add(org)
            await db.flush()

        team_slug = _slugify(settings.default_team_name)
        team = await db.scalar(
            select(Team).where(
                Team.org_id == org.id,
                Team.slug == team_slug,
            )
        )
        if team is None:
            team = Team(
                org_id=org.id,
                name=settings.default_team_name,
                slug=team_slug,
            )
            db.add(team)
            await db.flush()

        user = await db.scalar(select(User).where(User.email == settings.default_admin_email))
        password_hash = hash_password(settings.default_admin_password)
        if user is None:
            db.add(
                User(
                    org_id=org.id,
                    team_id=team.id,
                    email=settings.default_admin_email,
                    password_hash=password_hash,
                    role="super_admin",
                )
            )
            return

        user.org_id = org.id
        user.team_id = team.id
        user.password_hash = password_hash
        user.role = "super_admin"
        user.is_active = True


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"
