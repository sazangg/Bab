from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import AccessDeniedError
from app.modules.keys.schemas import (
    CreateProjectAllocationRequest,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ResolveAccessRequest,
    UpdateProjectAllocationRequest,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import CreateModelOfferingRequest, CreateProviderRequest


async def _create_actor_scope(db_session: AsyncSession):
    org = Organization(name=f"Allocation {uuid4()}", slug=f"allocation-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    return actor, Scope(org_id=org.id)


async def _create_project_provider_and_models(db_session: AsyncSession):
    actor, scope = await _create_actor_scope(db_session)
    project = await keys_facade.create_project(
        payload=CreateProjectRequest(name="Console", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="OpenAI", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    fast_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(
            provider_model_name="gpt-5.4-mini",
            alias="fast",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    large_model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name="gpt-5.5"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return actor, scope, project, provider, fast_model, large_model


async def test_project_allocation_grants_provider_access_for_all_models(
    db_session: AsyncSession,
) -> None:
    actor, scope, project, provider, *_ = await _create_project_provider_and_models(db_session)
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    allocation = await keys_facade.create_project_allocation(
        project_id=project.id,
        payload=CreateProjectAllocationRequest(provider_id=provider.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="gpt-5.4-mini",
            provider_id=provider.id,
        ),
        db=db_session,
    )

    assert allocation.model_offering_ids is None
    assert resolved.provider_id == provider.id
    assert resolved.provider_model == "gpt-5.4-mini"


async def test_project_allocation_can_restrict_to_specific_model_offerings(
    db_session: AsyncSession,
) -> None:
    actor, scope, project, provider, fast_model, _ = (
        await _create_project_provider_and_models(db_session)
    )
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.create_project_allocation(
        project_id=project.id,
        payload=CreateProjectAllocationRequest(
            provider_id=provider.id,
            model_offering_ids=[fast_model.id],
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    resolved = await keys_facade.resolve_access(
        payload=ResolveAccessRequest(
            raw_key=created_key.key,
            requested_model="gpt-5.4-mini",
            provider_id=provider.id,
        ),
        db=db_session,
    )
    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="gpt-5.5",
                provider_id=provider.id,
            ),
            db=db_session,
        )

    assert resolved.provider_model == "gpt-5.4-mini"


async def test_inactive_project_allocation_denies_access(db_session: AsyncSession) -> None:
    actor, scope, project, provider, *_ = await _create_project_provider_and_models(db_session)
    created_key = await keys_facade.create_virtual_key(
        project_id=project.id,
        payload=CreateVirtualKeyRequest(name="Console key"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.create_project_allocation(
        project_id=project.id,
        payload=CreateProjectAllocationRequest(provider_id=provider.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await keys_facade.update_project_allocation(
        project_id=project.id,
        provider_id=provider.id,
        payload=UpdateProjectAllocationRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(AccessDeniedError):
        await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=created_key.key,
                requested_model="gpt-5.4-mini",
                provider_id=provider.id,
            ),
            db=db_session,
        )
