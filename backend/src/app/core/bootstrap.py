import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, transaction
from app.core.security import hash_password
from app.modules.auth.internal.models import (  # noqa: F401
    IdentityAccount,
    Organization,
    OrganizationMembership,
    Team,
    TeamMembership,
    User,
)
from app.modules.providers.internal.models import (
    Provider,
)
from app.modules.settings.internal.models import OrganizationSettings  # noqa: F401

DEFAULT_ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


async def create_development_database() -> None:
    Path(settings.assets_dir).mkdir(parents=True, exist_ok=True)


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
                        supported_integration=entry["integration"],
                    )
                )
            else:
                provider.name = entry["name"]
                provider.display_name = entry["name"]
                provider.base_url = entry["base_url"]
                provider.adapter_type = "openai_compat"
                provider.description = entry["description"]
                provider.capabilities = entry["capabilities"]
                provider.supported_integration = entry["integration"]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"


def _provider_catalog_entries() -> list[dict]:
    return [
        {
            "name": "OpenAI",
            "slug": "openai",
            "base_url": "https://api.openai.com/v1",
            "description": "Official OpenAI API for GPT models.",
            "capabilities": {"chat": True, "streaming": True},
            "integration": "openai_compatible_default",
        },
        {
            "name": "OpenRouter",
            "slug": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "description": "Multi-provider OpenAI-compatible model router.",
            "capabilities": {"chat": True, "streaming": True},
            "integration": "openai_compatible_default",
        },
        {
            "name": "Anthropic",
            "slug": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "description": "Anthropic API with native Messages passthrough.",
            "capabilities": {},
            "integration": "anthropic_messages",
        },
    ]
