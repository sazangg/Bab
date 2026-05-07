from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.internal.models import Organization


@pytest.mark.asyncio
async def test_record_event_persists_audit_log(db_session: AsyncSession) -> None:
    org = Organization(name="Personal", slug="personal")
    db_session.add(org)
    await db_session.commit()

    event = await audit_facade.record_event(
        RecordAuditEvent(
            org_id=org.id,
            event="provider.created",
            target_type="provider",
            target_id=uuid4(),
            event_metadata={"name": "OpenAI"},
        ),
        db_session,
    )

    assert event.id is not None
    assert event.org_id == org.id
    assert event.event == "provider.created"
    assert event.event_metadata == {"name": "OpenAI"}


@pytest.mark.asyncio
async def test_list_events_is_scoped_and_limited(db_session: AsyncSession) -> None:
    first_org = Organization(name="Personal", slug="personal")
    second_org = Organization(name="Work", slug="work")
    db_session.add_all([first_org, second_org])
    await db_session.commit()

    await audit_facade.record_event(
        RecordAuditEvent(org_id=first_org.id, event="first.event"),
        db_session,
    )
    await audit_facade.record_event(
        RecordAuditEvent(org_id=first_org.id, event="second.event"),
        db_session,
    )
    await audit_facade.record_event(
        RecordAuditEvent(org_id=second_org.id, event="other_org.event"),
        db_session,
    )

    events = await audit_facade.list_events(org_id=first_org.id, db=db_session, limit=1)

    assert len(events) == 1
    assert events[0].org_id == first_org.id
    assert events[0].event in {"first.event", "second.event"}
