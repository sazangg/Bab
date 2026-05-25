import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine, transaction
from app.core.security import hash_password
from app.modules.activity.internal.models import ActivityEvent  # noqa: F401
from app.modules.auth.internal.models import (  # noqa: F401
    AuditEvent,
    IdentityAccount,
    Invite,
    Organization,
    OrganizationMembership,
    Team,
    TeamMembership,
    User,
)
from app.modules.guardrails.internal.models import (  # noqa: F401
    GuardrailAssignment,
    GuardrailEvent,
    GuardrailPolicy,
    GuardrailRule,
)
from app.modules.keys.internal.models import Allocation, Project, VirtualKey  # noqa: F401
from app.modules.providers.internal.models import (  # noqa: F401
    CredentialPool,
    CredentialPoolCredential,
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.settings.internal.models import OrganizationSettings  # noqa: F401
from app.modules.usage.internal.models import UsageRecord  # noqa: F401

DEFAULT_ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


async def create_development_database() -> None:
    Path(settings.assets_dir).mkdir(parents=True, exist_ok=True)
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
    if "is_favorite" not in provider_column_names:
        return True
    if "model_sync_mode" not in provider_column_names:
        return True
    teams_columns = await connection.exec_driver_sql("PRAGMA table_info(teams)")
    team_column_names = {row[1] for row in teams_columns}
    if "updated_at" not in team_column_names:
        return True

    projects_columns = await connection.exec_driver_sql("PRAGMA table_info(projects)")
    project_column_names = {row[1] for row in projects_columns}
    if "team_id" not in project_column_names:
        return True

    required_tables = {
        "users",
        "identity_accounts",
        "organization_memberships",
        "team_memberships",
        "invites",
        "audit_events",
        "provider_credentials",
        "credential_pools",
        "credential_pool_credentials",
        "allocations",
        "activity_events",
        "usage_records",
        "organization_settings",
        "guardrail_policies",
        "guardrail_rules",
        "guardrail_assignments",
        "guardrail_events",
    }
    for table_name in required_tables:
        existing = await connection.exec_driver_sql(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        )
        if existing.first() is None:
            return True

    provider_credentials_columns = await connection.exec_driver_sql(
        "PRAGMA table_info(provider_credentials)"
    )
    provider_credentials_column_info = {row[1]: row for row in provider_credentials_columns}
    if (
        "pool_id" in provider_credentials_column_info
        or "priority" in provider_credentials_column_info
    ):
        return True

    virtual_key_columns = await connection.exec_driver_sql("PRAGMA table_info(virtual_keys)")
    virtual_key_column_names = {row[1] for row in virtual_key_columns}
    if "allocation_id" not in virtual_key_column_names:
        return True
    if "custom_allocation_id" not in virtual_key_column_names:
        return True

    allocation_columns = await connection.exec_driver_sql("PRAGMA table_info(allocations)")
    allocation_column_names = {row[1] for row in allocation_columns}
    if "is_default" not in allocation_column_names or "budget_cents" not in allocation_column_names:
        return True

    usage_columns = await connection.exec_driver_sql("PRAGMA table_info(usage_records)")
    usage_column_names = {row[1] for row in usage_columns}
    if "cost_cents" not in usage_column_names:
        return True

    settings_columns = await connection.exec_driver_sql("PRAGMA table_info(organization_settings)")
    settings_column_names = {row[1] for row in settings_columns}
    return (
        "default_max_body_bytes" not in settings_column_names
        or "organization_logo_url" not in settings_column_names
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

        org_settings = await db.scalar(
            select(OrganizationSettings).where(OrganizationSettings.org_id == org.id)
        )
        if org_settings is None:
            db.add(
                OrganizationSettings(
                    org_id=org.id,
                    organization_name=org.name,
                    default_max_body_bytes=settings.proxy_max_body_bytes,
                )
            )

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
                description=None,
            )
            db.add(team)
            await db.flush()

        admin_email = settings.default_admin_email.lower()
        admin_user = await db.scalar(select(User).where(User.email == admin_email))
        if admin_user is None:
            admin_user = User(
                id=DEFAULT_ADMIN_USER_ID,
                email=admin_email,
                name="Default admin",
                password_hash=hash_password(settings.default_admin_password),
            )
            db.add(admin_user)
            await db.flush()
            db.add(
                IdentityAccount(
                    user_id=admin_user.id,
                    provider="local",
                    provider_subject=admin_email,
                    email=admin_email,
                )
            )
        elif not admin_user.password_hash:
            admin_user.password_hash = hash_password(settings.default_admin_password)

        org_membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == org.id,
                OrganizationMembership.user_id == admin_user.id,
            )
        )
        if org_membership is None:
            db.add(
                OrganizationMembership(
                    org_id=org.id,
                    user_id=admin_user.id,
                    role="org_owner",
                    status="active",
                )
            )
        else:
            org_membership.role = "org_owner"
            org_membership.status = "active"

        team_membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == admin_user.id,
            )
        )
        if team_membership is None:
            db.add(
                TeamMembership(
                    org_id=org.id,
                    team_id=team.id,
                    user_id=admin_user.id,
                    role="team_admin",
                )
            )

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
                        supported_integration="openai_compatible_default",
                    )
                )
            else:
                provider.name = entry["name"]
                provider.display_name = entry["name"]
                provider.base_url = entry["base_url"]
                provider.adapter_type = "openai_compat"
                provider.description = entry["description"]
                provider.capabilities = entry["capabilities"]
                provider.supported_integration = "openai_compatible_default"


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
            "name": "Google AI",
            "slug": "google-ai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "description": "Gemini models via Google AI Studio.",
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
        {
            "name": "DeepSeek",
            "slug": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "description": "DeepSeek chat and reasoning models.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Perplexity",
            "slug": "perplexity",
            "base_url": "https://api.perplexity.ai",
            "description": "Perplexity sonar models with built-in search.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Together AI",
            "slug": "together",
            "base_url": "https://api.together.xyz/v1",
            "description": "Open-source models hosted by Together.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Fireworks",
            "slug": "fireworks",
            "base_url": "https://api.fireworks.ai/inference/v1",
            "description": "Fast open-source inference hosted by Fireworks.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Cerebras",
            "slug": "cerebras",
            "base_url": "https://api.cerebras.ai/v1",
            "description": "Cerebras wafer-scale inference.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Hugging Face",
            "slug": "huggingface",
            "base_url": "https://api-inference.huggingface.co/v1",
            "description": "Inference Endpoints on the Hugging Face Hub.",
            "capabilities": default_capabilities,
        },
        {
            "name": "Ollama",
            "slug": "ollama",
            "base_url": "http://localhost:11434/v1",
            "description": "Local Ollama runtime exposed on this machine.",
            "capabilities": default_capabilities,
        },
    ]
