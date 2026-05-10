import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.providers.internal.models import Provider
from app.modules.request_logs.internal.models import RequestLog


async def _create_user(db_session: AsyncSession, *, slug: str, role: str = "team_manager") -> User:
    org = Organization(name=f"Org {slug}", slug=slug)
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{slug}@example.com",
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
async def test_authenticated_user_can_list_scoped_request_logs(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="request-logs-main")
    other_user = await _create_user(db_session, slug="request-logs-other")
    project = Project(org_id=user.org_id, created_by=user.id, name="Main")
    other_project = Project(org_id=other_user.org_id, created_by=other_user.id, name="Other")
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    other_provider = Provider(
        org_id=other_user.org_id,
        name="Other",
        base_url="https://other.example.test/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add_all([project, other_project, provider, other_provider])
    await db_session.flush()
    key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Main key",
        key_hash=hash_token("bab-sk-main"),
        key_prefix="bab-sk-main"[:16],
    )
    other_key = VirtualKey(
        org_id=other_user.org_id,
        project_id=other_project.id,
        name="Other key",
        key_hash=hash_token("bab-sk-other"),
        key_prefix="bab-sk-other"[:16],
    )
    db_session.add_all([key, other_key])
    await db_session.flush()
    db_session.add_all(
        [
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=key.id,
                provider_id=provider.id,
                requested_model="fast-default",
                provider_model="gpt-5.4-mini",
                http_status=200,
                latency_ms=12,
                usage_source="unknown",
            ),
            RequestLog(
                org_id=other_user.org_id,
                project_id=other_project.id,
                virtual_key_id=other_key.id,
                provider_id=other_provider.id,
                requested_model="other",
                provider_model="other",
                http_status=200,
                latency_ms=1,
                usage_source="unknown",
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/request-logs", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["requested_model"] == "fast-default"
    assert body[0]["provider_model"] == "gpt-5.4-mini"
    assert body[0]["usage_source"] == "unknown"
    assert "messages" not in body[0]


@pytest.mark.asyncio
async def test_authenticated_user_can_filter_and_page_request_logs(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="request-logs-filter")
    project = Project(org_id=user.org_id, created_by=user.id, name="Main")
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add_all([project, provider])
    await db_session.flush()
    key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Main key",
        key_hash=hash_token("bab-sk-main"),
        key_prefix="bab-sk-main"[:16],
    )
    db_session.add(key)
    await db_session.flush()
    db_session.add_all(
        [
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=key.id,
                provider_id=provider.id,
                requested_model="fast-default",
                provider_model="gpt-5.4-mini",
                http_status=200,
                latency_ms=12,
                usage_source="unknown",
            ),
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=key.id,
                provider_id=provider.id,
                requested_model="slow-default",
                provider_model="gpt-5.4",
                http_status=500,
                latency_ms=14,
                usage_source="unknown",
            ),
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=key.id,
                provider_id=provider.id,
                requested_model="fast-default",
                provider_model="gpt-5.4-mini",
                http_status=200,
                latency_ms=15,
                usage_source="unknown",
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        filtered_response = await client.get(
            "/api/v1/request-logs",
            params={"status_code": 200, "requested_model": "fast-default", "limit": 10},
            headers=_auth_headers(user),
        )
        paged_response = await client.get(
            "/api/v1/request-logs",
            params={"limit": 1, "offset": 1},
            headers=_auth_headers(user),
        )

    assert filtered_response.status_code == 200
    assert [item["requested_model"] for item in filtered_response.json()] == [
        "fast-default",
        "fast-default",
    ]
    assert paged_response.status_code == 200
    assert len(paged_response.json()) == 1
