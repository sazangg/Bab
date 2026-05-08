import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project


async def _create_user(db_session: AsyncSession, *, role: str = "team_manager") -> User:
    org = Organization(name=f"Org {role}", slug=f"project-org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"project-{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_authenticated_user_can_create_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/projects",
            headers=_auth_headers(user),
            json={"name": "Inbox Assistant", "description": "Personal email triage"},
        )

    body = response.json()
    project = await db_session.scalar(select(Project))
    audit_log = await db_session.scalar(select(AuditLog).where(AuditLog.event == "project.created"))

    assert response.status_code == 201
    assert body["name"] == "Inbox Assistant"
    assert body["description"] == "Personal email triage"
    assert project is not None
    assert project.org_id == user.org_id
    assert project.created_by == user.id
    assert audit_log is not None
    assert audit_log.actor_user_id == user.id


@pytest.mark.asyncio
async def test_authenticated_user_can_list_scoped_projects(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    other_user = await _create_user(db_session, role="org_admin")
    db_session.add_all(
        [
            Project(org_id=user.org_id, created_by=user.id, name="Mine"),
            Project(org_id=other_user.org_id, created_by=other_user.id, name="Other"),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/projects", headers=_auth_headers(user))

    assert response.status_code == 200
    assert [project["name"] for project in response.json()] == ["Mine"]


@pytest.mark.asyncio
async def test_authenticated_user_can_update_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = Project(org_id=user.org_id, created_by=user.id, name="Old")
    db_session.add(project)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=_auth_headers(user),
            json={"name": "New", "description": "Updated"},
        )

    await db_session.refresh(project)
    audit_log = await db_session.scalar(select(AuditLog).where(AuditLog.event == "project.updated"))

    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert project.name == "New"
    assert project.description == "Updated"
    assert audit_log is not None


@pytest.mark.asyncio
async def test_authenticated_user_can_clear_project_description(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = Project(org_id=user.org_id, created_by=user.id, name="With notes", description="Old")
    db_session.add(project)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=_auth_headers(user),
            json={"description": None},
        )

    await db_session.refresh(project)

    assert response.status_code == 200
    assert response.json()["description"] is None
    assert project.description is None


@pytest.mark.asyncio
async def test_authenticated_user_can_deactivate_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = Project(org_id=user.org_id, created_by=user.id, name="Inbox Assistant")
    db_session.add(project)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/projects/{project.id}",
            headers=_auth_headers(user),
        )

    await db_session.refresh(project)

    assert response.status_code == 204
    assert project.is_active is False


@pytest.mark.asyncio
async def test_project_not_found_is_scoped_to_org(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    other_user = await _create_user(db_session, role="super_admin")
    project = Project(org_id=other_user.org_id, created_by=other_user.id, name="Other")
    db_session.add(project)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{project.id}",
            headers=_auth_headers(user),
            json={"name": "Nope"},
        )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
