from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.policies import read_models as policy_read_models
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.providers.internal import repository
from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.providers.schemas import (
    ProviderImpactPolicy,
    ProviderImpactResponse,
    ProviderResourceImpactResponse,
)
from app.modules.usage import read_models as usage_read_models


async def get_provider_impact(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderImpactResponse:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    return await _compose_provider_impact(org_id=scope.org_id, provider_id=provider_id, db=db)


async def get_provider_credential_impact(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResourceImpactResponse:
    credential = await _get_provider_credential_or_raise(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    return await _compose_credential_impact(org_id=scope.org_id, credential=credential, db=db)


async def get_credential_pool_impact(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResourceImpactResponse:
    pool = await _get_credential_pool_or_raise(
        provider_id=provider_id,
        pool_id=pool_id,
        scope=scope,
        db=db,
    )
    return await _compose_pool_impact(org_id=scope.org_id, pool=pool, db=db)


async def get_model_offering_impact(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResourceImpactResponse:
    model = await _get_model_offering_or_raise(
        provider_id=provider_id,
        model_offering_id=model_offering_id,
        scope=scope,
        db=db,
    )
    return await _compose_model_impact(org_id=scope.org_id, model=model, db=db)


async def _compose_provider_impact(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> ProviderImpactResponse:
    policy_impacts = await policy_read_models.list_provider_route_impacts(
        org_id=org_id,
        provider_id=provider_id,
        db=db,
    )
    policies = [
        ProviderImpactPolicy(
            id=policy.policy_id,
            name=policy.policy_name,
            route_id=policy.route_id,
        )
        for policy in policy_impacts
    ]
    limit_rule_count = await policy_read_models.count_provider_limit_rules(
        org_id=org_id,
        provider_id=provider_id,
        db=db,
    )
    pool_count = int(
        await db.scalar(
            select(func.count(CredentialPool.id)).where(
                CredentialPool.org_id == org_id,
                CredentialPool.provider_id == provider_id,
                CredentialPool.is_active.is_(True),
            )
        )
        or 0
    )
    model_count = int(
        await db.scalar(
            select(func.count(ModelOffering.id)).where(
                ModelOffering.org_id == org_id,
                ModelOffering.provider_id == provider_id,
                ModelOffering.is_active.is_(True),
            )
        )
        or 0
    )
    since = datetime.now(UTC) - timedelta(days=30)
    usage = await usage_read_models.get_recent_provider_usage_summary(
        org_id=org_id,
        provider_id=provider_id,
        since=since,
        db=db,
    )
    return ProviderImpactResponse(
        access_policies=policies,
        active_limit_rule_count=limit_rule_count,
        active_pool_count=pool_count,
        active_model_count=model_count,
        recent_usage_window_days=30,
        recent_request_count=usage.request_count,
        recent_cost_cents=usage.cost_cents,
    )


async def _compose_credential_impact(
    *,
    org_id: UUID,
    credential: ProviderCredential,
    db: AsyncSession,
):
    memberships = int(
        await db.scalar(
            select(func.count(CredentialPoolCredential.id))
            .join(CredentialPool, CredentialPool.id == CredentialPoolCredential.pool_id)
            .where(
                CredentialPoolCredential.org_id == org_id,
                CredentialPoolCredential.provider_credential_id == credential.id,
                CredentialPoolCredential.is_active.is_(True),
                CredentialPool.is_active.is_(True),
            )
        )
        or 0
    )
    currently_routable = await _provider_is_routable(
        org_id=org_id, provider_id=credential.provider_id, db=db
    )
    routable_without_target = await _provider_is_routable(
        org_id=org_id,
        provider_id=credential.provider_id,
        excluded_credential_id=credential.id,
        db=db,
    )
    usage = await usage_read_models.get_recent_provider_credential_usage_summary(
        org_id=org_id,
        provider_credential_id=credential.id,
        since=_recent_usage_since(),
        db=db,
    )
    return ProviderResourceImpactResponse(
        active_pool_membership_count=memberships,
        recent_request_count=usage.request_count,
        recent_cost_cents=usage.cost_cents,
        leaves_provider_unroutable=(
            credential.is_active and currently_routable and not routable_without_target
        ),
    )


async def _compose_pool_impact(*, org_id: UUID, pool: CredentialPool, db: AsyncSession):
    policies = await _policy_routes_to_response(
        org_id=org_id,
        credential_pool_id=pool.id,
        db=db,
    )
    rules = await policy_read_models.count_provider_limit_rules(
        org_id=org_id,
        credential_pool_id=pool.id,
        db=db,
    )
    currently_routable = await _provider_is_routable(
        org_id=org_id, provider_id=pool.provider_id, db=db
    )
    routable_without_target = await _provider_is_routable(
        org_id=org_id,
        provider_id=pool.provider_id,
        excluded_pool_id=pool.id,
        db=db,
    )
    return ProviderResourceImpactResponse(
        access_policies=policies,
        active_limit_rule_count=rules,
        leaves_provider_unroutable=(
            pool.is_active and currently_routable and not routable_without_target
        ),
    )


async def _compose_model_impact(*, org_id: UUID, model: ModelOffering, db: AsyncSession):
    policies = await _policy_routes_to_response(
        org_id=org_id,
        model_offering_id=model.id,
        db=db,
    )
    rules = await policy_read_models.count_provider_limit_rules(
        org_id=org_id,
        model_offering_id=model.id,
        db=db,
    )
    currently_routable = await _provider_is_routable(
        org_id=org_id, provider_id=model.provider_id, db=db
    )
    routable_without_target = await _provider_is_routable(
        org_id=org_id,
        provider_id=model.provider_id,
        excluded_model_id=model.id,
        db=db,
    )
    usage = await usage_read_models.get_recent_provider_model_usage_summary(
        org_id=org_id,
        provider_id=model.provider_id,
        provider_model=model.provider_model_name,
        since=_recent_usage_since(),
        db=db,
    )
    return ProviderResourceImpactResponse(
        access_policies=policies,
        active_limit_rule_count=rules,
        recent_request_count=usage.request_count,
        recent_cost_cents=usage.cost_cents,
        leaves_provider_unroutable=(
            model.is_active and currently_routable and not routable_without_target
        ),
    )


async def _provider_is_routable(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
    excluded_credential_id: UUID | None = None,
    excluded_pool_id: UUID | None = None,
    excluded_model_id: UUID | None = None,
) -> bool:
    provider_active = bool(
        await db.scalar(
            select(Provider.is_active).where(
                Provider.org_id == org_id,
                Provider.id == provider_id,
            )
        )
    )
    if not provider_active:
        return False

    model_filters = [
        ModelOffering.org_id == org_id,
        ModelOffering.provider_id == provider_id,
        ModelOffering.is_active.is_(True),
    ]
    if excluded_model_id is not None:
        model_filters.append(ModelOffering.id != excluded_model_id)
    has_active_model = bool(
        await db.scalar(select(ModelOffering.id).where(*model_filters).limit(1))
    )
    if not has_active_model:
        return False

    chain_filters = [
        CredentialPool.org_id == org_id,
        CredentialPool.provider_id == provider_id,
        CredentialPool.is_active.is_(True),
        CredentialPoolCredential.org_id == org_id,
        CredentialPoolCredential.is_active.is_(True),
        ProviderCredential.org_id == org_id,
        ProviderCredential.provider_id == provider_id,
        ProviderCredential.is_active.is_(True),
    ]
    if excluded_pool_id is not None:
        chain_filters.append(CredentialPool.id != excluded_pool_id)
    if excluded_credential_id is not None:
        chain_filters.append(ProviderCredential.id != excluded_credential_id)
    return bool(
        await db.scalar(
            select(CredentialPoolCredential.id)
            .join(CredentialPool, CredentialPool.id == CredentialPoolCredential.pool_id)
            .join(
                ProviderCredential,
                ProviderCredential.id == CredentialPoolCredential.provider_credential_id,
            )
            .where(*chain_filters)
            .limit(1)
        )
    )


async def _policy_routes_to_response(
    *,
    org_id: UUID,
    db: AsyncSession,
    credential_pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
):
    route_impacts = await policy_read_models.list_provider_route_impacts(
        org_id=org_id,
        credential_pool_id=credential_pool_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    return [
        ProviderImpactPolicy(
            id=impact.policy_id,
            name=impact.policy_name,
            route_id=impact.route_id,
        )
        for impact in route_impacts
    ]


def _recent_usage_since() -> datetime:
    return datetime.now(UTC) - timedelta(days=30)


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


async def _get_provider_credential_or_raise(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredential:
    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if provider_credential is None or provider_credential.provider_id != provider_id:
        raise ProviderNotFoundError
    return provider_credential


async def _get_credential_pool_or_raise(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPool:
    pool = await repository.get_credential_pool(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    if pool is None or pool.provider_id != provider_id:
        raise ProviderNotFoundError
    return pool


async def _get_model_offering_or_raise(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ModelOffering:
    model_offering = await repository.get_model_offering(
        org_id=scope.org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    if model_offering is None or model_offering.provider_id != provider_id:
        raise ProviderNotFoundError
    return model_offering
