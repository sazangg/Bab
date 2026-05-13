import re

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine, transaction
from app.modules.audit.internal.models import AuditLog  # noqa: F401
from app.modules.auth.internal.models import Organization, Team  # noqa: F401
from app.modules.keys.internal.models import (  # noqa: F401
    ModelAlias,
    Project,
    ProjectProviderAccess,
    ProjectSubscriptionAccess,
    Subscription,
    SubscriptionModelAccess,
    SubscriptionProviderKey,
    VirtualKey,
)
from app.modules.limits.internal.models import LimitCounter, LimitPolicy  # noqa: F401
from app.modules.providers.internal.models import Provider, ProviderKey, ProviderModel  # noqa: F401
from app.modules.request_logs.internal.models import RequestLog  # noqa: F401


async def create_development_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
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

        for entry in _provider_catalog_entries():
            provider = await db.scalar(
                select(Provider).where(
                    Provider.org_id == org.id,
                    Provider.slug == entry["slug"],
                )
            )
            if provider is None:
                db.add(
                    Provider(
                        org_id=org.id,
                        name=entry["name"],
                        display_name=entry["name"],
                        slug=entry["slug"],
                        base_url=entry["base_url"],
                        adapter_type="openai_compat",
                        description=entry["description"],
                        capabilities=entry["capabilities"],
                        supported_integration="openai_compatible",
                    )
                )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"


def _provider_catalog_entries() -> list[dict]:
    default_capabilities = {
        "chat": True,
        "embeddings": False,
        "vision": False,
        "tools": False,
        "json_mode": False,
        "streaming": True,
    }
    return [
        {
            "name": "OpenAI",
            "slug": "openai",
            "base_url": "https://api.openai.com/v1",
            "description": "Official OpenAI API for GPT models.",
            "capabilities": default_capabilities,
        },
        {
            "name": "OpenRouter",
            "slug": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "description": "Multi-provider OpenAI-compatible model router.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Mistral AI",
            "slug": "mistral",
            "base_url": "https://api.mistral.ai/v1",
            "description": "Mistral hosted models through their v1 API.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Groq",
            "slug": "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "description": "Groq OpenAI-compatible inference endpoint.",
            "capabilities": default_capabilities,
        },
    ]
