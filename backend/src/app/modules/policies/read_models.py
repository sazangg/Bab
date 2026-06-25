from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicyRule,
)


class ProviderPolicyRouteImpact(BaseModel):
    policy_id: UUID
    policy_name: str
    route_id: UUID


async def list_provider_route_impacts(
    *,
    org_id: UUID,
    db: AsyncSession,
    provider_id: UUID | None = None,
    credential_pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
) -> list[ProviderPolicyRouteImpact]:
    filters = _route_filters(
        org_id=org_id,
        provider_id=provider_id,
        credential_pool_id=credential_pool_id,
        model_offering_id=model_offering_id,
    )
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
        .where(*filters)
        .order_by(AccessPolicy.name)
    )
    return [
        ProviderPolicyRouteImpact(policy_id=policy_id, policy_name=name, route_id=route_id)
        for policy_id, name, route_id in rows
    ]


async def count_provider_limit_rules(
    *,
    org_id: UUID,
    db: AsyncSession,
    provider_id: UUID | None = None,
    credential_pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
) -> int:
    filters = [
        LimitPolicyRule.org_id == org_id,
        LimitPolicyRule.is_active.is_(True),
    ]
    if provider_id is not None:
        filters.append(LimitPolicyRule.provider_id == provider_id)
    if credential_pool_id is not None:
        filters.append(LimitPolicyRule.credential_pool_id == credential_pool_id)
    if model_offering_id is not None:
        filters.append(LimitPolicyRule.model_offering_id == model_offering_id)
    return int(await db.scalar(select(func.count(LimitPolicyRule.id)).where(*filters)) or 0)


def _route_filters(
    *,
    org_id: UUID,
    provider_id: UUID | None,
    credential_pool_id: UUID | None,
    model_offering_id: UUID | None,
):
    filters = [
        AccessPolicy.org_id == org_id,
        AccessPolicy.is_active.is_(True),
        AccessPolicyPublicModel.is_active.is_(True),
        AccessPolicyRouteCandidate.is_active.is_(True),
    ]
    if provider_id is not None:
        filters.append(AccessPolicyRouteCandidate.provider_id == provider_id)
    if credential_pool_id is not None:
        filters.append(AccessPolicyRouteCandidate.credential_pool_id == credential_pool_id)
    if model_offering_id is not None:
        filters.append(AccessPolicyRouteCandidate.model_offering_id == model_offering_id)
    return filters
