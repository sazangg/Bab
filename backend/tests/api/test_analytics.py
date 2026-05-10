from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.providers.internal.models import Provider
from app.modules.request_logs.internal.models import RequestLog


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
async def test_authenticated_user_can_read_scoped_analytics_summary(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="analytics-main")
    other_user = await _create_user(db_session, slug="analytics-other")
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
    second_key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Second key",
        key_hash=hash_token("bab-sk-second"),
        key_prefix="bab-sk-second"[:16],
    )
    other_key = VirtualKey(
        org_id=other_user.org_id,
        project_id=other_project.id,
        name="Other key",
        key_hash=hash_token("bab-sk-other"),
        key_prefix="bab-sk-other"[:16],
    )
    db_session.add_all([key, second_key, other_key])
    await db_session.flush()
    now = datetime.now(UTC)
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
                latency_ms=10,
                prompt_tokens=6,
                completion_tokens=14,
                total_tokens=20,
                usage_source="provider_reported",
                created_at=now - timedelta(hours=1),
            ),
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=key.id,
                provider_id=provider.id,
                requested_model="fast-default",
                provider_model="gpt-5.4-mini",
                http_status=429,
                latency_ms=30,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                usage_source="unknown",
                error_code="limit_exceeded",
                created_at=now - timedelta(days=1),
            ),
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=second_key.id,
                provider_id=provider.id,
                requested_model="slow",
                provider_model="gpt-5.4",
                http_status=200,
                latency_ms=20,
                prompt_tokens=9,
                completion_tokens=11,
                total_tokens=20,
                usage_source="estimated",
                created_at=now - timedelta(days=10),
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
                total_tokens=100,
                usage_source="provider_reported",
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/v1/analytics/summary?days=7&recent_limit=1",
            headers=_auth_headers(user),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {
        "request_count": 2,
        "success_count": 1,
        "error_count": 1,
        "prompt_tokens": 6,
        "completion_tokens": 14,
        "total_tokens": 20,
        "average_latency_ms": 20,
    }
    assert len(body["recent_requests"]) == 1
    assert body["recent_requests"][0]["requested_model"] == "fast-default"
    assert body["recent_requests"][0]["total_tokens"] == 20
    assert body["top_keys"] == [
        {
            "virtual_key_id": str(key.id),
            "key_name": "Main key",
            "request_count": 2,
            "total_tokens": 20,
        }
    ]
    assert len(body["time_series"]) == 2
    assert sum(point["request_count"] for point in body["time_series"]) == 2


@pytest.mark.asyncio
async def test_analytics_summary_returns_empty_shape_without_logs(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="analytics-empty")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/analytics/summary", headers=_auth_headers(user))

    assert response.status_code == 200
    assert response.json() == {
        "totals": {
            "request_count": 0,
            "success_count": 0,
            "error_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "average_latency_ms": None,
        },
        "recent_requests": [],
        "top_keys": [],
        "time_series": [],
    }


@pytest.mark.asyncio
async def test_authenticated_user_can_read_key_usage(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="analytics-key-main")
    other_user = await _create_user(db_session, slug="analytics-key-other")
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
        key_hash=hash_token("bab-sk-key-main"),
        key_prefix="bab-sk-key-main"[:16],
    )
    second_key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Second key",
        key_hash=hash_token("bab-sk-key-second"),
        key_prefix="bab-sk-key-second"[:16],
    )
    other_key = VirtualKey(
        org_id=other_user.org_id,
        project_id=other_project.id,
        name="Other key",
        key_hash=hash_token("bab-sk-key-other"),
        key_prefix="bab-sk-key-other"[:16],
    )
    db_session.add_all([key, second_key, other_key])
    await db_session.flush()
    now = datetime.now(UTC)
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
                latency_ms=10,
                prompt_tokens=4,
                completion_tokens=6,
                total_tokens=10,
                usage_source="provider_reported",
                created_at=now - timedelta(hours=1),
            ),
            RequestLog(
                org_id=user.org_id,
                project_id=project.id,
                virtual_key_id=second_key.id,
                provider_id=provider.id,
                requested_model="second",
                provider_model="gpt-5.4",
                http_status=200,
                latency_ms=20,
                total_tokens=50,
                usage_source="estimated",
                created_at=now - timedelta(hours=1),
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
                total_tokens=100,
                usage_source="provider_reported",
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/analytics/keys/{key.id}?days=7&recent_limit=5",
            headers=_auth_headers(user),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["virtual_key_id"] == str(key.id)
    assert body["key_name"] == "Main key"
    assert body["totals"]["request_count"] == 1
    assert body["totals"]["total_tokens"] == 10
    assert len(body["recent_requests"]) == 1
    assert body["recent_requests"][0]["virtual_key_id"] == str(key.id)
    assert len(body["time_series"]) == 1


@pytest.mark.asyncio
async def test_key_usage_returns_404_for_other_org_key(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="analytics-key-visible")
    other_user = await _create_user(db_session, slug="analytics-key-hidden")
    other_project = Project(org_id=other_user.org_id, created_by=other_user.id, name="Other")
    db_session.add(other_project)
    await db_session.flush()
    other_key = VirtualKey(
        org_id=other_user.org_id,
        project_id=other_project.id,
        name="Other key",
        key_hash=hash_token("bab-sk-hidden"),
        key_prefix="bab-sk-hidden"[:16],
    )
    db_session.add(other_key)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/analytics/keys/{other_key.id}",
            headers=_auth_headers(user),
        )

    assert response.status_code == 404
