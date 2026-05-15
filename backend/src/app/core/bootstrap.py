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
from app.modules.providers.internal.models import (  # noqa: F401
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.request_logs.internal.models import RequestLog  # noqa: F401


async def create_development_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            if await _sqlite_schema_is_stale(connection):
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)


async def _sqlite_schema_is_stale(connection) -> bool:
    providers_columns = await connection.exec_driver_sql("PRAGMA table_info(providers)")
    provider_column_names = {row[1] for row in providers_columns}
    if "display_name" not in provider_column_names:
        return True
    if "credential_routing_policy" not in provider_column_names:
        return True

    provider_credentials = await connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_credentials'"
    )
    if provider_credentials.first() is None:
        return True

    model_offerings = await connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='model_offerings'"
    )
    if model_offerings.first() is None:
        return True

    model_offering_columns = await connection.exec_driver_sql("PRAGMA table_info(model_offerings)")
    model_offering_column_names = {row[1] for row in model_offering_columns}
    required_model_offering_columns = {
        "input_modalities",
        "output_modalities",
        "metadata_source",
        "metadata_last_synced_at",
    }
    return not required_model_offering_columns.issubset(model_offering_column_names)


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
