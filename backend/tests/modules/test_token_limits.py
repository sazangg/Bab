from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.limits.errors import LimitExceededError
from app.modules.limits.facade import reconcile_token_limits, reserve_proxy_limits
from app.modules.limits.internal.models import LimitCounter, LimitPolicy
from app.modules.limits.schemas import LimitEvaluationContext


async def _create_context_with_token_policy(
    db_session: AsyncSession,
    *,
    limit_value: int,
) -> LimitEvaluationContext:
    org = Organization(name="Token Limit Org", slug="token-limit-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="token-limit@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(org_id=org.id, created_by=user.id, name="Token limited")
    db_session.add(project)
    await db_session.flush()
    key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Token key",
        key_hash=hash_token("bab-sk-token"),
        key_prefix="bab-sk-token"[:16],
    )
    db_session.add(key)
    await db_session.flush()
    db_session.add(
        LimitPolicy(
            org_id=org.id,
            scope_type="project",
            scope_id=project.id,
            metric="token_count",
            window="day",
            limit_value=limit_value,
        )
    )
    await db_session.commit()
    return LimitEvaluationContext(
        org_id=org.id,
        project_id=project.id,
        virtual_key_id=key.id,
        provider_id=org.id,
        provider_model="gpt-5.4-mini",
    )


@pytest.mark.asyncio
async def test_token_limit_reserves_estimate_before_provider_call(db_session: AsyncSession) -> None:
    context = await _create_context_with_token_policy(db_session, limit_value=10)
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    await reserve_proxy_limits(context=context, estimated_tokens=6, db=db_session, now=now)

    with pytest.raises(LimitExceededError):
        await reserve_proxy_limits(context=context, estimated_tokens=5, db=db_session, now=now)


@pytest.mark.asyncio
async def test_token_limit_reconciles_actual_usage_after_provider_call(
    db_session: AsyncSession,
) -> None:
    context = await _create_context_with_token_policy(db_session, limit_value=20)
    now = datetime(2026, 5, 9, 12, 30, 10, tzinfo=UTC)

    reservations = await reserve_proxy_limits(
        context=context,
        estimated_tokens=6,
        db=db_session,
        now=now,
    )
    await reconcile_token_limits(
        reservations=reservations,
        actual_tokens=9,
        estimated_tokens=6,
        db=db_session,
    )

    counter = await db_session.scalar(select(LimitCounter))

    assert counter is not None
    assert counter.consumed_amount == 9
