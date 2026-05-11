from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import hash_password, hash_token
from app.modules.auth.internal.models import Organization, User
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import AccessDeniedError, InvalidVirtualKeyError
from app.modules.keys.facade import resolve_access
from app.modules.keys.internal.models import (
    ModelAlias,
    Project,
    ProjectProviderAccess,
    VirtualKey,
)
from app.modules.keys.schemas import (
    AttachSubscriptionProviderKeyRequest,
    CreateProjectRequest,
    CreateSubscriptionRequest,
    GrantProjectSubscriptionAccessRequest,
    ResolveAccessRequest,
    SetSubscriptionModelAccessRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal.models import Provider
from app.modules.providers.schemas import (
    CreateProviderKeyRequest,
    CreateProviderModelRequest,
    CreateProviderRequest,
)


async def _create_graph(
    db_session: AsyncSession,
    *,
    raw_key: str = "bab-sk-test-key",
    project_models: list[str] | None = None,
    key_restrictions: list[dict[str, object]] | None = None,
    expires_at: datetime | None = None,
) -> tuple[Organization, Project, Provider, VirtualKey]:
    org = Organization(name="Access Org", slug="access-resolution-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="access-resolution@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(org_id=org.id, created_by=user.id, name="Inbox Assistant")
    provider = Provider(
        org_id=org.id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add_all([project, provider])
    await db_session.flush()
    db_session.add(
        ProjectProviderAccess(
            org_id=org.id,
            project_id=project.id,
            provider_id=provider.id,
            allowed_models=project_models,
        )
    )
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Local dev",
        key_hash=hash_token(raw_key),
        key_prefix=raw_key[:16],
        restrictions=key_restrictions,
        expires_at=expires_at,
    )
    db_session.add(virtual_key)
    await db_session.commit()
    return org, project, provider, virtual_key


async def _create_subscription_graph(
    db_session: AsyncSession,
    *,
    provider_name: str = "OpenAI",
    provider_model_name: str = "gpt-5.4-mini",
    model_alias: str | None = "fast",
    subscription_priority: int = 100,
    raw_key: str = "bab-sk-test-key",
) -> tuple[Organization, Project, Provider, VirtualKey]:
    org = Organization(name=f"{provider_name} Access Org", slug=f"{provider_name.lower()}-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{provider_name.lower()}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.commit()

    scope = Scope(org_id=org.id)
    project = await keys_facade.create_project(
        payload=CreateProjectRequest(name="Inbox Assistant"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name=provider_name,
            base_url="https://api.example.com/v1",
            api_key="legacy-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    provider_key = await providers_facade.create_provider_key(
        provider_id=provider.id,
        payload=CreateProviderKeyRequest(name="Production", api_key="sk-secret"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_model(
        provider_id=provider.id,
        payload=CreateProviderModelRequest(
            provider_model_name=provider_model_name,
            alias=model_alias,
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    subscription = await keys_facade.create_subscription(
        payload=CreateSubscriptionRequest(name=f"{provider_name} subscription"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await keys_facade.attach_provider_key_to_subscription(
        subscription_id=subscription.id,
        payload=AttachSubscriptionProviderKeyRequest(provider_key_id=provider_key.id),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await keys_facade.grant_project_subscription_access(
        project_id=project.id,
        payload=GrantProjectSubscriptionAccessRequest(
            subscription_id=subscription.id,
            priority=subscription_priority,
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Local dev",
        key_hash=hash_token(raw_key),
        key_prefix=raw_key[:16],
    )
    db_session.add(virtual_key)
    await db_session.commit()
    return org, project, provider, virtual_key


@pytest.mark.asyncio
async def test_resolve_access_allows_direct_provider_model(
    db_session: AsyncSession,
) -> None:
    _, project, provider, virtual_key = await _create_graph(
        db_session,
        project_models=["gpt-5.4-mini"],
    )

    resolved = await resolve_access(
        payload=ResolveAccessRequest(
            raw_key="bab-sk-test-key",
            provider_id=provider.id,
            requested_model="gpt-5.4-mini",
        ),
        db=db_session,
    )

    assert resolved.project_id == project.id
    assert resolved.virtual_key_id == virtual_key.id
    assert resolved.provider_id == provider.id
    assert resolved.provider_model == "gpt-5.4-mini"
    assert resolved.used_alias is False


@pytest.mark.asyncio
async def test_resolve_access_uses_active_model_alias(
    db_session: AsyncSession,
) -> None:
    org, _, provider, _ = await _create_graph(
        db_session,
        project_models=["gpt-5.4-mini"],
    )
    db_session.add(
        ModelAlias(
            org_id=org.id,
            alias="fast-default",
            provider_id=provider.id,
            provider_model="gpt-5.4-mini",
        )
    )
    await db_session.commit()

    resolved = await resolve_access(
        payload=ResolveAccessRequest(raw_key="bab-sk-test-key", requested_model="fast-default"),
        db=db_session,
    )

    assert resolved.provider_id == provider.id
    assert resolved.provider_model == "gpt-5.4-mini"
    assert resolved.used_alias is True


@pytest.mark.asyncio
async def test_resolve_access_rejects_invalid_key(db_session: AsyncSession) -> None:
    await _create_graph(db_session)

    with pytest.raises(InvalidVirtualKeyError):
        await resolve_access(
            payload=ResolveAccessRequest(
                raw_key="bab-sk-wrong",
                requested_model="gpt-5.4-mini",
            ),
            db=db_session,
        )


@pytest.mark.asyncio
async def test_resolve_access_rejects_expired_key(db_session: AsyncSession) -> None:
    await _create_graph(db_session, expires_at=datetime.now(UTC) - timedelta(minutes=1))

    with pytest.raises(InvalidVirtualKeyError):
        await resolve_access(
            payload=ResolveAccessRequest(
                raw_key="bab-sk-test-key",
                requested_model="gpt-5.4-mini",
            ),
            db=db_session,
        )


@pytest.mark.asyncio
async def test_resolve_access_rejects_model_outside_project_access(
    db_session: AsyncSession,
) -> None:
    _, _, provider, _ = await _create_graph(db_session, project_models=["gpt-5.4-mini"])

    with pytest.raises(AccessDeniedError):
        await resolve_access(
            payload=ResolveAccessRequest(
                raw_key="bab-sk-test-key",
                provider_id=provider.id,
                requested_model="gpt-5.4",
            ),
            db=db_session,
        )


@pytest.mark.asyncio
async def test_resolve_access_intersects_key_restrictions_with_project_access(
    db_session: AsyncSession,
) -> None:
    _, _, provider, _ = await _create_graph(
        db_session,
        project_models=None,
    )
    key = await db_session.scalar(select(VirtualKey).where(VirtualKey.name == "Local dev"))
    assert key is not None
    key.restrictions = [{"provider_id": str(provider.id), "allowed_models": ["gpt-5.4-mini"]}]
    await db_session.commit()

    with pytest.raises(AccessDeniedError):
        await resolve_access(
            payload=ResolveAccessRequest(
                raw_key="bab-sk-test-key",
                provider_id=provider.id,
                requested_model="gpt-5.4",
            ),
            db=db_session,
        )

    resolved = await resolve_access(
        payload=ResolveAccessRequest(
            raw_key="bab-sk-test-key",
            provider_id=provider.id,
            requested_model="gpt-5.4-mini",
        ),
        db=db_session,
    )
    assert resolved.provider_model == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_resolve_access_uses_subscription_provider_model_alias(
    db_session: AsyncSession,
) -> None:
    _, project, provider, virtual_key = await _create_subscription_graph(db_session)

    resolved = await resolve_access(
        payload=ResolveAccessRequest(raw_key="bab-sk-test-key", requested_model="fast"),
        db=db_session,
    )

    assert resolved.project_id == project.id
    assert resolved.virtual_key_id == virtual_key.id
    assert resolved.provider_id == provider.id
    assert resolved.provider_model == "gpt-5.4-mini"
    assert resolved.used_alias is True


@pytest.mark.asyncio
async def test_resolve_access_prefers_lower_priority_subscription_for_alias_conflict(
    db_session: AsyncSession,
) -> None:
    org, project, _, _ = await _create_subscription_graph(
        db_session,
        provider_name="OpenAI",
        provider_model_name="gpt-5.4-mini",
        model_alias="fast",
        subscription_priority=50,
    )
    user = await db_session.scalar(select(User).where(User.org_id == org.id))
    assert user is not None
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Mistral",
            base_url="https://api.mistral.example/v1",
            api_key="legacy-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    provider_key = await providers_facade.create_provider_key(
        provider_id=provider.id,
        payload=CreateProviderKeyRequest(name="Production", api_key="sk-mistral"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_model(
        provider_id=provider.id,
        payload=CreateProviderModelRequest(
            provider_model_name="mistral-small-latest",
            alias="fast",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    subscription = await keys_facade.create_subscription(
        payload=CreateSubscriptionRequest(name="Mistral subscription"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await keys_facade.attach_provider_key_to_subscription(
        subscription_id=subscription.id,
        payload=AttachSubscriptionProviderKeyRequest(provider_key_id=provider_key.id),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await keys_facade.grant_project_subscription_access(
        project_id=project.id,
        payload=GrantProjectSubscriptionAccessRequest(
            subscription_id=subscription.id,
            priority=10,
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )

    resolved = await resolve_access(
        payload=ResolveAccessRequest(raw_key="bab-sk-test-key", requested_model="fast"),
        db=db_session,
    )

    assert resolved.provider_id == provider.id
    assert resolved.provider_model == "mistral-small-latest"


@pytest.mark.asyncio
async def test_resolve_access_respects_subscription_model_narrowing(
    db_session: AsyncSession,
) -> None:
    org, project, provider, _ = await _create_subscription_graph(
        db_session,
        provider_model_name="gpt-5.4",
        model_alias="smart",
    )
    user = await db_session.scalar(select(User).where(User.org_id == org.id))
    assert user is not None
    scope = Scope(org_id=org.id)
    fast_model = await providers_facade.create_provider_model(
        provider_id=provider.id,
        payload=CreateProviderModelRequest(provider_model_name="gpt-5.4-mini", alias="fast"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    subscription_access = await keys_facade.list_project_subscription_access(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )
    assert len(subscription_access) == 1
    await keys_facade.set_subscription_model_access(
        subscription_id=subscription_access[0].subscription_id,
        payload=SetSubscriptionModelAccessRequest(provider_model_ids=[fast_model.id]),
        actor=user,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await resolve_access(
            payload=ResolveAccessRequest(raw_key="bab-sk-test-key", requested_model="smart"),
            db=db_session,
        )

    resolved = await resolve_access(
        payload=ResolveAccessRequest(raw_key="bab-sk-test-key", requested_model="fast"),
        db=db_session,
    )

    assert resolved.provider_model == "gpt-5.4-mini"
