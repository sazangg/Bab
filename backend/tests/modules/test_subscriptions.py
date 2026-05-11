from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import hash_password
from app.modules.auth.internal.models import Organization, User
from app.modules.keys import facade as keys_facade
from app.modules.keys.schemas import (
    AttachSubscriptionProviderKeyRequest,
    CreateProjectRequest,
    CreateSubscriptionRequest,
    GrantProjectSubscriptionAccessRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import CreateProviderKeyRequest, CreateProviderRequest


async def _create_user(db_session: AsyncSession) -> User:
    org = Organization(name="Subscription Org", slug="subscription-org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="subscriptions@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_subscription_can_attach_provider_key(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    scope = Scope(org_id=user.org_id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
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

    subscription = await keys_facade.create_subscription(
        payload=CreateSubscriptionRequest(name="Default AI", description="Shared AI access"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    attached = await keys_facade.attach_provider_key_to_subscription(
        subscription_id=subscription.id,
        payload=AttachSubscriptionProviderKeyRequest(
            provider_key_id=provider_key.id,
            priority=25,
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    attachments = await keys_facade.list_subscription_provider_keys(
        subscription_id=subscription.id,
        scope=scope,
        db=db_session,
    )

    assert subscription.name == "Default AI"
    assert attached.subscription_id == subscription.id
    assert attached.provider_key_id == provider_key.id
    assert attached.priority == 25
    assert [item.id for item in attachments] == [attached.id]


async def test_project_can_be_granted_subscription_access_with_priority(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    scope = Scope(org_id=user.org_id)
    project = await keys_facade.create_project(
        payload=CreateProjectRequest(name="Inbox Assistant"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    subscription = await keys_facade.create_subscription(
        payload=CreateSubscriptionRequest(name="Default AI"),
        actor=user,
        scope=scope,
        db=db_session,
    )

    access = await keys_facade.grant_project_subscription_access(
        project_id=project.id,
        payload=GrantProjectSubscriptionAccessRequest(
            subscription_id=subscription.id,
            priority=10,
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    access_rules = await keys_facade.list_project_subscription_access(
        project_id=project.id,
        scope=scope,
        db=db_session,
    )

    assert access.project_id == project.id
    assert access.subscription_id == subscription.id
    assert access.priority == 10
    assert [rule.id for rule in access_rules] == [access.id]
