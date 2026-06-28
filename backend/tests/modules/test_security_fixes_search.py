"""Regression test for LIKE/ILIKE wildcard escaping in search (#30)."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import RecordActivityEvent
from app.modules.workspace.internal.models import Organization


@pytest.mark.asyncio
async def test_activity_search_escapes_like_wildcards(db_session: AsyncSession) -> None:
    org = Organization(name="Search", slug=f"search-{uuid4()}")
    db_session.add(org)
    await db_session.commit()

    for message in ("alpha beta", "alpha%beta"):
        await activity_facade.record_event_and_commit(
            payload=RecordActivityEvent(
                org_id=org.id,
                category="proxy",
                severity="info",
                action="test.event",
                message=message,
            ),
            db=db_session,
        )

    # A literal "%" must match only the row containing a literal "%", not every row
    # (which an unescaped LIKE wildcard would do).
    results = await activity_facade.list_events(org_id=org.id, search="%", db=db_session)
    assert {event.message for event in results} == {"alpha%beta"}
