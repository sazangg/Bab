from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.modules.auth import facade as auth_facade
from app.modules.auth.internal.models import OrganizationMembership, User
from app.modules.auth.schemas import LoginRequest
from app.modules.providers.internal.models import Provider
from app.modules.workspace.internal.models import Organization


class _SessionContext:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncSession:
        return self._db

    async def __aexit__(self, *_exc_info) -> None:
        return None


def _patch_cli_session(monkeypatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionContext(db_session))

    async def current(_engine):
        return {"is_current": True}

    monkeypatch.setattr(cli, "get_migration_state", current)
    monkeypatch.setattr(cli, "validate_bootstrap_settings", lambda: None)


@pytest.mark.asyncio
async def test_bootstrap_empty_database_creates_owner_and_catalog(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    validator_calls = 0

    def validate_bootstrap_settings() -> None:
        nonlocal validator_calls
        validator_calls += 1

    monkeypatch.setattr(cli, "validate_bootstrap_settings", validate_bootstrap_settings)

    await cli._bootstrap(
        organization_name="Production Org",
        admin_email="Owner@Example.com",
        admin_password="correct-password",
    )

    user = await db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert user is not None
    membership = await db_session.scalar(
        select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
    )
    assert membership is not None
    assert membership.role == "org_owner"
    assert await db_session.scalar(select(func.count(Provider.id))) > 0
    assert validator_calls == 1

    token_response, _refresh_token = await auth_facade.login(
        LoginRequest(email="owner@example.com", password="correct-password"),
        db_session,
    )
    assert token_response.token_type == "bearer"


@pytest.mark.asyncio
async def test_bootstrap_refuses_non_empty_database_without_changing_owner(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    org = Organization(name="Existing", slug=f"existing-{uuid4()}")
    user = User(email="existing@example.com", name="Existing", password_hash="hash")
    db_session.add_all([org, user])
    await db_session.commit()

    with pytest.raises(SystemExit, match="empty organization table"):
        await cli._bootstrap(
            organization_name="Production Org",
            admin_email="owner@example.com",
            admin_password="correct-password",
        )

    assert await db_session.scalar(select(func.count(Organization.id))) == 1
    assert await db_session.scalar(select(func.count(User.id))) == 1
    existing_user = await db_session.scalar(
        select(User).where(User.email == "existing@example.com")
    )
    assert existing_user is not None
    assert existing_user.password_hash == "hash"


@pytest.mark.asyncio
async def test_bootstrap_refuses_non_current_database(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    _patch_cli_session(monkeypatch, db_session)

    async def not_current(_engine):
        return {"is_current": False}

    monkeypatch.setattr(cli, "get_migration_state", not_current)

    with pytest.raises(SystemExit, match="current migration head"):
        await cli._bootstrap(
            organization_name="Production Org",
            admin_email="owner@example.com",
            admin_password="correct-password",
        )

    assert await db_session.scalar(select(func.count(Organization.id))) == 0
