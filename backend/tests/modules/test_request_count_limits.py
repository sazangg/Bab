from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.errors import RequestLimitExceededError
from app.modules.keys.facade import enforce_request_count_limits
from app.modules.keys.internal.models import Project, VirtualKey, VirtualKeyRequestCounter
from app.modules.keys.schemas import ResolvedAccess


async def _create_limited_key(
    db_session: AsyncSession,
    *,
    per_minute: int | None = None,
    per_day: int | None = None,
) -> tuple[ResolvedAccess, VirtualKey]:
    org = Organization(name="Limit Org", slug="limit-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="limit@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(org_id=org.id, created_by=user.id, name="Limited")
    db_session.add(project)
    await db_session.flush()
    key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Limited key",
        key_hash=hash_token("bab-sk-limit"),
        key_prefix="bab-sk-limit"[:16],
        request_limit_per_minute=per_minute,
        request_limit_per_day=per_day,
    )
    db_session.add(key)
    await db_session.commit()
    resolved = ResolvedAccess(
        org_id=org.id,
        project_id=project.id,
        virtual_key_id=key.id,
        provider_id=org.id,
        requested_model="gpt-5.4-mini",
        provider_model="gpt-5.4-mini",
        used_alias=False,
    )
    return resolved, key


@pytest.mark.asyncio
async def test_request_count_limit_allows_until_boundary(db_session: AsyncSession) -> None:
    resolved, key = await _create_limited_key(db_session, per_minute=2)
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    await enforce_request_count_limits(resolved=resolved, db=db_session, now=now)
    await enforce_request_count_limits(resolved=resolved, db=db_session, now=now)

    with pytest.raises(RequestLimitExceededError):
        await enforce_request_count_limits(resolved=resolved, db=db_session, now=now)

    counters = (await db_session.scalars(select(VirtualKeyRequestCounter))).all()
    assert len(counters) == 1
    assert counters[0].virtual_key_id == key.id
    assert counters[0].request_count == 2
    assert counters[0].window_kind == "minute"
    assert counters[0].window_start.replace(tzinfo=UTC) == datetime(2026, 5, 9, 12, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_request_count_limit_uses_separate_windows(db_session: AsyncSession) -> None:
    resolved, _ = await _create_limited_key(db_session, per_day=1)
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    await enforce_request_count_limits(resolved=resolved, db=db_session, now=now)

    with pytest.raises(RequestLimitExceededError):
        await enforce_request_count_limits(resolved=resolved, db=db_session, now=now)

    await enforce_request_count_limits(
        resolved=resolved, db=db_session, now=now + timedelta(days=1)
    )
