import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.internal.models import Organization, User


async def _create_user(db_session: AsyncSession, *, slug: str) -> User:
    org = Organization(name=f"Org {slug}", slug=slug)
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{slug}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="team_manager",
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_authenticated_user_can_list_scoped_audit_logs(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="audit-main")
    other_user = await _create_user(db_session, slug="audit-other")
    await audit_facade.record_event(
        RecordAuditEvent(
            org_id=user.org_id,
            actor_user_id=user.id,
            event="provider.created",
            target_type="provider",
            event_metadata={"name": "OpenAI"},
        ),
        db_session,
    )
    await audit_facade.record_event(
        RecordAuditEvent(org_id=other_user.org_id, event="other.event"),
        db_session,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/audit-logs", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event"] == "provider.created"
    assert body[0]["event_metadata"] == {"name": "OpenAI"}
