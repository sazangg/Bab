from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap
from app.core.security import hash_password, verify_password
from app.modules.auth.internal.models import Organization, Team, User


async def test_sync_default_workspace_updates_existing_default_admin(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    existing_org = Organization(name="Old Org", slug="old-org")
    db_session.add(existing_org)
    await db_session.flush()
    db_session.add(
        User(
            org_id=existing_org.id,
            email="admin@example.com",
            password_hash=hash_password("old-password"),
            role="org_admin",
            is_active=False,
        )
    )
    await db_session.commit()

    monkeypatch.setattr(bootstrap.settings, "default_organization_name", "Default Organization")
    monkeypatch.setattr(bootstrap.settings, "default_team_name", "Default Team")
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "new-password-123")

    await bootstrap.sync_default_workspace(db_session)

    org = await db_session.scalar(
        select(Organization).where(Organization.slug == "default-organization")
    )
    team = await db_session.scalar(select(Team).where(Team.slug == "default-team"))
    user = await db_session.scalar(select(User).where(User.email == "admin@example.com"))

    assert org is not None
    assert team is not None
    assert user is not None
    assert user.org_id == org.id
    assert user.team_id == team.id
    assert user.role == "super_admin"
    assert user.is_active
    assert verify_password("new-password-123", user.password_hash)
