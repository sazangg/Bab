from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.facade import record_event
from app.modules.activity.internal.models import ActivityEvent
from app.modules.activity.schemas import RecordActivityEvent
from app.modules.audit.internal.models import AuditEvent
from app.modules.audit.internal.service import record_audit_event
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser


@pytest.mark.asyncio
async def test_activity_metadata_redacts_nested_secret_fields(db_session: AsyncSession) -> None:
    org = Organization(name=f"Metadata {uuid4()}", slug=f"metadata-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    project_id = uuid4()

    await record_event(
        payload=RecordActivityEvent(
            org_id=org.id,
            category="settings",
            severity="info",
            action="settings.updated",
            message="Updated settings.",
            metadata={
                "project_id": str(project_id),
                "request_id": "req_123",
                "api_key": "sk-secret",
                "nested": {
                    "authorization": "Bearer secret",
                    "provider_id": str(uuid4()),
                    "items": [{"password": "hidden", "virtual_key_id": str(uuid4())}],
                },
            },
        ),
        db=db_session,
    )
    await db_session.commit()

    event = await db_session.scalar(select(ActivityEvent).where(ActivityEvent.org_id == org.id))
    assert event is not None
    assert event.metadata_["api_key"] == "[redacted]"
    assert event.metadata_["nested"]["authorization"] == "[redacted]"
    assert event.metadata_["nested"]["items"][0]["password"] == "[redacted]"
    assert event.metadata_["project_id"] == str(project_id)
    assert event.metadata_["request_id"] == "req_123"


@pytest.mark.asyncio
async def test_audit_metadata_redacts_nested_secret_fields(db_session: AsyncSession) -> None:
    org = Organization(name=f"Audit Metadata {uuid4()}", slug=f"audit-metadata-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="org_admin",
        permissions=["*"],
    )
    team_id = uuid4()

    await record_audit_event(
        actor=actor,
        action="settings.updated",
        entity_type="organization",
        entity_id=None,
        metadata={
            "team_id": str(team_id),
            "token": "secret",
            "credentials": {"secret": "hidden", "key": "hidden", "project_id": str(uuid4())},
        },
        db=db_session,
    )
    await db_session.commit()

    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.org_id == org.id))
    assert event is not None
    assert event.metadata_["token"] == "[redacted]"
    assert event.metadata_["credentials"]["secret"] == "[redacted]"
    assert event.metadata_["credentials"]["key"] == "[redacted]"
    assert event.metadata_["team_id"] == str(team_id)
    assert "project_id" in event.metadata_["credentials"]
