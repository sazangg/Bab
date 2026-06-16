from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicyRule,
)
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
from app.modules.usage.internal.models import UsageRecord


async def get_provider_impact(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> ProviderImpactResponse:
    policy_rows = await db.execute(
        select(AccessPolicy.id, AccessPolicy.name, AccessPolicyRouteCandidate.id)
        .join(
            AccessPolicyPublicModel,
            AccessPolicyPublicModel.access_policy_id == AccessPolicy.id,
        )
        .join(
            AccessPolicyRouteCandidate,
            AccessPolicyRouteCandidate.public_model_id == AccessPolicyPublicModel.id,
        )
        .where(
            AccessPolicy.org_id == org_id,
            AccessPolicyRouteCandidate.provider_id == provider_id,
            AccessPolicy.is_active.is_(True),
            AccessPolicyPublicModel.is_active.is_(True),
            AccessPolicyRouteCandidate.is_active.is_(True),
        )
        .order_by(AccessPolicy.name)
    )
    policies = [
        ProviderImpactPolicy(id=policy_id, name=name, route_id=route_id)
        for policy_id, name, route_id in policy_rows
    ]
    limit_rule_count = int(
        await db.scalar(
            select(func.count(LimitPolicyRule.id)).where(
                LimitPolicyRule.org_id == org_id,
                LimitPolicyRule.provider_id == provider_id,
                LimitPolicyRule.is_active.is_(True),
            )
        )
        or 0
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
    usage = (
        await db.execute(
            select(
                func.count(UsageRecord.id),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
            ).where(
                UsageRecord.org_id == org_id,
                UsageRecord.provider_id == provider_id,
                UsageRecord.created_at >= since,
            )
        )
    ).one()
    return ProviderImpactResponse(
        access_policies=policies,
        active_limit_rule_count=limit_rule_count,
        active_pool_count=pool_count,
        active_model_count=model_count,
        recent_usage_window_days=30,
        recent_request_count=int(usage[0]),
        recent_cost_cents=int(usage[1]),
    )


async def get_credential_impact(*, org_id: UUID, credential: ProviderCredential, db: AsyncSession):
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
    usage = await _usage_summary(
        org_id=org_id,
        db=db,
        filters=[UsageRecord.provider_credential_id == credential.id],
    )
    return ProviderResourceImpactResponse(
        active_pool_membership_count=memberships,
        recent_request_count=usage[0],
        recent_cost_cents=usage[1],
        leaves_provider_unroutable=(
            credential.is_active and currently_routable and not routable_without_target
        ),
    )


async def get_pool_impact(*, org_id: UUID, pool: CredentialPool, db: AsyncSession):
    policies = await _policy_routes(
        org_id=org_id,
        filter_clause=AccessPolicyRouteCandidate.credential_pool_id == pool.id,
        db=db,
    )
    rules = int(
        await db.scalar(
            select(func.count(LimitPolicyRule.id)).where(
                LimitPolicyRule.org_id == org_id,
                LimitPolicyRule.credential_pool_id == pool.id,
                LimitPolicyRule.is_active.is_(True),
            )
        )
        or 0
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


async def get_model_impact(*, org_id: UUID, model: ModelOffering, db: AsyncSession):
    rows = await db.execute(
        select(AccessPolicy, AccessPolicyRouteCandidate)
        .join(
            AccessPolicyPublicModel,
            AccessPolicyPublicModel.access_policy_id == AccessPolicy.id,
        )
        .join(
            AccessPolicyRouteCandidate,
            AccessPolicyRouteCandidate.public_model_id == AccessPolicyPublicModel.id,
        )
        .where(
            AccessPolicy.org_id == org_id,
            AccessPolicy.is_active.is_(True),
            AccessPolicyPublicModel.is_active.is_(True),
            AccessPolicyRouteCandidate.is_active.is_(True),
            AccessPolicyRouteCandidate.model_offering_id == model.id,
        )
    )
    policies = [
        ProviderImpactPolicy(id=policy.id, name=policy.name, route_id=candidate.id)
        for policy, candidate in rows
    ]
    rules = int(
        await db.scalar(
            select(func.count(LimitPolicyRule.id)).where(
                LimitPolicyRule.org_id == org_id,
                LimitPolicyRule.model_offering_id == model.id,
                LimitPolicyRule.is_active.is_(True),
            )
        )
        or 0
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
    usage = await _usage_summary(
        org_id=org_id,
        db=db,
        filters=[
            UsageRecord.provider_id == model.provider_id,
            UsageRecord.provider_model == model.provider_model_name,
        ],
    )
    return ProviderResourceImpactResponse(
        access_policies=policies,
        active_limit_rule_count=rules,
        recent_request_count=usage[0],
        recent_cost_cents=usage[1],
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


async def _policy_routes(*, org_id: UUID, filter_clause, db: AsyncSession):
    rows = await db.execute(
        select(AccessPolicy.id, AccessPolicy.name, AccessPolicyRouteCandidate.id)
        .join(
            AccessPolicyPublicModel,
            AccessPolicyPublicModel.access_policy_id == AccessPolicy.id,
        )
        .join(
            AccessPolicyRouteCandidate,
            AccessPolicyRouteCandidate.public_model_id == AccessPolicyPublicModel.id,
        )
        .where(
            AccessPolicy.org_id == org_id,
            AccessPolicy.is_active.is_(True),
            AccessPolicyPublicModel.is_active.is_(True),
            AccessPolicyRouteCandidate.is_active.is_(True),
            filter_clause,
        )
    )
    return [ProviderImpactPolicy(id=item[0], name=item[1], route_id=item[2]) for item in rows]


async def _usage_summary(*, org_id: UUID, filters: list, db: AsyncSession) -> tuple[int, int]:
    row = (
        await db.execute(
            select(
                func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.cost_cents), 0)
            ).where(
                UsageRecord.org_id == org_id,
                UsageRecord.created_at >= datetime.now(UTC) - timedelta(days=30),
                *filters,
            )
        )
    ).one()
    return int(row[0]), int(row[1])
