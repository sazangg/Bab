from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.keys.schemas import ResolvedAccess
from app.modules.limits.errors import LimitExceededError
from app.modules.limits.facade import reserve_proxy_limits
from app.modules.limits.internal.models import LimitCounter, LimitPolicy
from app.modules.limits.schemas import LimitEvaluationContext


async def _create_resolved_context(db_session: AsyncSession) -> LimitEvaluationContext:
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
    )
    db_session.add(key)
    await db_session.commit()
    return LimitEvaluationContext(
        org_id=org.id,
        project_id=project.id,
        virtual_key_id=key.id,
        provider_id=org.id,
        provider_model="gpt-5.4-mini",
    )


async def _create_policy(
    db_session: AsyncSession,
    *,
    context: LimitEvaluationContext,
    scope_type: str,
    scope_id,
    metric: str,
    window: str,
    limit_value: int,
    scope_value: str | None = None,
) -> LimitPolicy:
    policy = LimitPolicy(
        org_id=context.org_id,
        scope_type=scope_type,
        scope_id=scope_id,
        scope_value=scope_value,
        metric=metric,
        window=window,
        limit_value=limit_value,
    )
    db_session.add(policy)
    await db_session.commit()
    return policy


@pytest.mark.asyncio
async def test_request_count_limit_allows_until_boundary(db_session: AsyncSession) -> None:
    context = await _create_resolved_context(db_session)
    policy = await _create_policy(
        db_session,
        context=context,
        scope_type="virtual_key",
        scope_id=context.virtual_key_id,
        metric="request_count",
        window="minute",
        limit_value=2,
    )
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)
    await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)

    with pytest.raises(LimitExceededError):
        await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)

    counters = (await db_session.scalars(select(LimitCounter))).all()
    assert len(counters) == 1
    assert counters[0].policy_id == policy.id
    assert counters[0].consumed_amount == 2
    assert counters[0].window_start.replace(tzinfo=UTC) == datetime(2026, 5, 9, 12, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_request_count_limit_uses_separate_windows(db_session: AsyncSession) -> None:
    context = await _create_resolved_context(db_session)
    await _create_policy(
        db_session,
        context=context,
        scope_type="org",
        scope_id=context.org_id,
        metric="request_count",
        window="day",
        limit_value=1,
    )
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)

    with pytest.raises(LimitExceededError):
        await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)

    await reserve_proxy_limits(
        context=context, estimated_tokens=5, db=db_session, now=now + timedelta(days=1)
    )


@pytest.mark.asyncio
async def test_provider_model_scope_matches_provider_and_model(db_session: AsyncSession) -> None:
    context = await _create_resolved_context(db_session)
    await _create_policy(
        db_session,
        context=context,
        scope_type="provider_model",
        scope_id=context.provider_id,
        scope_value=context.provider_model,
        metric="request_count",
        window="minute",
        limit_value=1,
    )

    await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session)

    different_model = ResolvedAccess(
        org_id=context.org_id,
        project_id=context.project_id,
        virtual_key_id=context.virtual_key_id,
        provider_id=context.provider_id,
        requested_model="gpt-5.4",
        provider_model="gpt-5.4",
        used_alias=False,
    )
    await reserve_proxy_limits(
        context=LimitEvaluationContext(**different_model.model_dump()),
        estimated_tokens=5,
        db=db_session,
    )
