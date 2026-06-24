from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
    LimitPolicyRule,
    LimitPolicyRuleMatcher,
    LimitPolicyRulePartition,
)
from app.modules.policy_kernel.models import PolicyRevision


async def create_access_policy(
    *,
    org_id: UUID,
    name: str,
    description: str | None,
    is_active: bool,
    policy_id: UUID,
    owning_scope_type: str | None = None,
    owning_team_id: UUID | None = None,
    owning_project_id: UUID | None = None,
    owning_virtual_key_id: UUID | None = None,
    db: AsyncSession,
) -> AccessPolicy:
    policy = AccessPolicy(
        org_id=org_id,
        policy_id=policy_id,
        name=name,
        description=description,
        is_active=is_active,
        owning_scope_type=owning_scope_type,
        owning_team_id=owning_team_id,
        owning_project_id=owning_project_id,
        owning_virtual_key_id=owning_virtual_key_id,
    )
    db.add(policy)
    await db.flush()
    return policy


async def list_access_policies(*, org_id: UUID, db: AsyncSession) -> list[AccessPolicy]:
    result = await db.scalars(
        select(AccessPolicy)
        .where(AccessPolicy.org_id == org_id)
        .order_by(AccessPolicy.created_at.desc())
    )
    return list(result)


async def get_access_policy(
    *, policy_id: UUID, org_id: UUID, db: AsyncSession
) -> AccessPolicy | None:
    return await db.scalar(
        select(AccessPolicy).where(AccessPolicy.id == policy_id, AccessPolicy.org_id == org_id)
    )


async def get_access_policy_by_shared_policy(
    *, shared_policy_id: UUID, org_id: UUID, db: AsyncSession
) -> AccessPolicy | None:
    return await db.scalar(
        select(AccessPolicy).where(
            AccessPolicy.policy_id == shared_policy_id,
            AccessPolicy.org_id == org_id,
        )
    )


async def create_access_policy_public_model(
    *,
    org_id: UUID,
    access_policy_id: UUID | None,
    public_model_name: str,
    routing_mode: str,
    fallback_on: list[str],
    max_route_attempts: int | None,
    is_active: bool,
    db: AsyncSession,
    policy_revision_id: UUID,
) -> AccessPolicyPublicModel:
    public_model = AccessPolicyPublicModel(
        org_id=org_id,
        access_policy_id=access_policy_id,
        policy_revision_id=policy_revision_id,
        public_model_name=public_model_name,
        routing_mode=routing_mode,
        fallback_on=fallback_on,
        max_route_attempts=max_route_attempts,
        is_active=is_active,
    )
    db.add(public_model)
    await db.flush()
    return public_model


async def get_access_policy_revision_public_model_by_name(
    *,
    org_id: UUID,
    policy_revision_id: UUID,
    public_model_name: str,
    db: AsyncSession,
) -> AccessPolicyPublicModel | None:
    return await db.scalar(
        select(AccessPolicyPublicModel).where(
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.policy_revision_id == policy_revision_id,
            AccessPolicyPublicModel.public_model_name == public_model_name,
        )
    )


async def get_access_policy_public_model_by_name(
    *,
    org_id: UUID,
    access_policy_id: UUID,
    public_model_name: str,
    db: AsyncSession,
) -> AccessPolicyPublicModel | None:
    return await db.scalar(
        select(AccessPolicyPublicModel).where(
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.access_policy_id == access_policy_id,
            AccessPolicyPublicModel.public_model_name == public_model_name,
        )
    )


async def list_access_policy_public_models(
    *, org_id: UUID, access_policy_id: UUID, db: AsyncSession
) -> list[AccessPolicyPublicModel]:
    result = await db.scalars(
        select(AccessPolicyPublicModel)
        .where(
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.access_policy_id == access_policy_id,
        )
        .order_by(AccessPolicyPublicModel.created_at.asc())
    )
    return list(result)


async def list_access_policy_revision_public_models(
    *, org_id: UUID, policy_revision_id: UUID, db: AsyncSession
) -> list[AccessPolicyPublicModel]:
    result = await db.scalars(
        select(AccessPolicyPublicModel)
        .where(
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.policy_revision_id == policy_revision_id,
        )
        .order_by(AccessPolicyPublicModel.created_at.asc())
    )
    return list(result)


async def delete_access_policy_public_models(
    *, org_id: UUID, access_policy_id: UUID, db: AsyncSession
) -> None:
    await db.execute(
        update(AccessPolicyPublicModel)
        .where(
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.access_policy_id == access_policy_id,
        )
        .values(access_policy_id=None)
    )
    await db.flush()


async def create_access_policy_route_candidate(
    *,
    org_id: UUID,
    public_model_id: UUID,
    provider_id: UUID,
    credential_pool_id: UUID,
    model_offering_id: UUID,
    priority: int,
    weight: int,
    is_active: bool,
    db: AsyncSession,
    provider_model_offering_id: UUID | None = None,
) -> AccessPolicyRouteCandidate:
    candidate = AccessPolicyRouteCandidate(
        org_id=org_id,
        public_model_id=public_model_id,
        provider_id=provider_id,
        credential_pool_id=credential_pool_id,
        model_offering_id=model_offering_id,
        provider_model_offering_id=provider_model_offering_id or model_offering_id,
        priority=priority,
        weight=weight,
        is_active=is_active,
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def list_access_policy_route_candidates(
    *, org_id: UUID, public_model_id: UUID, db: AsyncSession
) -> list[AccessPolicyRouteCandidate]:
    result = await db.scalars(
        select(AccessPolicyRouteCandidate)
        .where(
            AccessPolicyRouteCandidate.org_id == org_id,
            AccessPolicyRouteCandidate.public_model_id == public_model_id,
        )
        .order_by(
            AccessPolicyRouteCandidate.priority,
            AccessPolicyRouteCandidate.weight.desc(),
            AccessPolicyRouteCandidate.created_at,
        )
    )
    return list(result)


async def list_access_policy_revision_route_candidates(
    *, org_id: UUID, policy_revision_id: UUID, db: AsyncSession
) -> list[AccessPolicyRouteCandidate]:
    result = await db.scalars(
        select(AccessPolicyRouteCandidate)
        .join(
            AccessPolicyPublicModel,
            AccessPolicyPublicModel.id == AccessPolicyRouteCandidate.public_model_id,
        )
        .where(
            AccessPolicyRouteCandidate.org_id == org_id,
            AccessPolicyPublicModel.org_id == org_id,
            AccessPolicyPublicModel.policy_revision_id == policy_revision_id,
        )
        .order_by(
            AccessPolicyPublicModel.public_model_name,
            AccessPolicyRouteCandidate.priority,
            AccessPolicyRouteCandidate.weight.desc(),
            AccessPolicyRouteCandidate.created_at,
        )
    )
    return list(result)


async def create_limit_policy(
    *,
    org_id: UUID,
    values: dict,
    db: AsyncSession,
    policy_id: UUID,
) -> LimitPolicy:
    policy = LimitPolicy(org_id=org_id, policy_id=policy_id, **values)
    db.add(policy)
    await db.flush()
    return policy


async def list_limit_policies(*, org_id: UUID, db: AsyncSession) -> list[LimitPolicy]:
    result = await db.scalars(
        select(LimitPolicy)
        .where(LimitPolicy.org_id == org_id)
        .order_by(LimitPolicy.created_at.desc())
    )
    return list(result)


async def get_limit_policy(
    *, policy_id: UUID, org_id: UUID, db: AsyncSession
) -> LimitPolicy | None:
    return await db.scalar(
        select(LimitPolicy).where(LimitPolicy.id == policy_id, LimitPolicy.org_id == org_id)
    )


async def get_limit_policy_by_shared_policy(
    *, shared_policy_id: UUID, org_id: UUID, db: AsyncSession
) -> LimitPolicy | None:
    return await db.scalar(
        select(LimitPolicy).where(
            LimitPolicy.policy_id == shared_policy_id,
            LimitPolicy.org_id == org_id,
        )
    )


async def create_limit_policy_rule(
    *,
    org_id: UUID,
    limit_policy_id: UUID,
    values: dict,
    db: AsyncSession,
    policy_revision_id: UUID,
) -> LimitPolicyRule:
    rule = LimitPolicyRule(
        org_id=org_id,
        limit_policy_id=limit_policy_id,
        policy_revision_id=policy_revision_id,
        **values,
    )
    db.add(rule)
    await db.flush()
    return rule


async def list_limit_policy_rules(
    *, org_id: UUID, limit_policy_id: UUID, db: AsyncSession
) -> list[LimitPolicyRule]:
    result = await db.scalars(
        select(LimitPolicyRule)
        .join(LimitPolicy, LimitPolicy.id == LimitPolicyRule.limit_policy_id)
        .join(PolicyRevision, PolicyRevision.policy_id == LimitPolicy.policy_id)
        .where(
            LimitPolicyRule.org_id == org_id,
            LimitPolicyRule.limit_policy_id == limit_policy_id,
            LimitPolicy.org_id == org_id,
            PolicyRevision.org_id == org_id,
            PolicyRevision.status == "active",
            LimitPolicyRule.policy_revision_id == PolicyRevision.id,
        )
        .order_by(LimitPolicyRule.created_at.asc())
    )
    return list(result)


async def list_limit_policy_revision_rules(
    *, org_id: UUID, limit_policy_id: UUID, policy_revision_id: UUID, db: AsyncSession
) -> list[LimitPolicyRule]:
    result = await db.scalars(
        select(LimitPolicyRule)
        .where(
            LimitPolicyRule.org_id == org_id,
            LimitPolicyRule.limit_policy_id == limit_policy_id,
            LimitPolicyRule.policy_revision_id == policy_revision_id,
        )
        .order_by(LimitPolicyRule.created_at.asc())
    )
    return list(result)


async def get_limit_policy_rule(
    *, rule_id: UUID, org_id: UUID, db: AsyncSession
) -> LimitPolicyRule | None:
    return await db.scalar(
        select(LimitPolicyRule).where(
            LimitPolicyRule.id == rule_id,
            LimitPolicyRule.org_id == org_id,
        )
    )


async def create_limit_policy_rule_matcher(
    *,
    org_id: UUID,
    rule_id: UUID,
    dimension: str,
    operator: str,
    value_json: object | None,
    db: AsyncSession,
) -> LimitPolicyRuleMatcher:
    matcher = LimitPolicyRuleMatcher(
        org_id=org_id,
        rule_id=rule_id,
        dimension=dimension,
        operator=operator,
        value_json=value_json,
    )
    db.add(matcher)
    await db.flush()
    return matcher


async def list_limit_policy_rule_matchers(
    *, org_id: UUID, rule_id: UUID, db: AsyncSession
) -> list[LimitPolicyRuleMatcher]:
    result = await db.scalars(
        select(LimitPolicyRuleMatcher)
        .where(
            LimitPolicyRuleMatcher.org_id == org_id,
            LimitPolicyRuleMatcher.rule_id == rule_id,
        )
        .order_by(LimitPolicyRuleMatcher.created_at.asc(), LimitPolicyRuleMatcher.id.asc())
    )
    return list(result)


async def delete_limit_policy_rule_matchers(
    *, org_id: UUID, rule_id: UUID, db: AsyncSession
) -> None:
    await db.execute(
        delete(LimitPolicyRuleMatcher).where(
            LimitPolicyRuleMatcher.org_id == org_id,
            LimitPolicyRuleMatcher.rule_id == rule_id,
        )
    )


async def create_limit_policy_rule_partition(
    *,
    org_id: UUID,
    rule_id: UUID,
    dimension: str,
    position: int,
    db: AsyncSession,
) -> LimitPolicyRulePartition:
    partition = LimitPolicyRulePartition(
        org_id=org_id,
        rule_id=rule_id,
        dimension=dimension,
        position=position,
    )
    db.add(partition)
    await db.flush()
    return partition


async def list_limit_policy_rule_partitions(
    *, org_id: UUID, rule_id: UUID, db: AsyncSession
) -> list[LimitPolicyRulePartition]:
    result = await db.scalars(
        select(LimitPolicyRulePartition)
        .where(
            LimitPolicyRulePartition.org_id == org_id,
            LimitPolicyRulePartition.rule_id == rule_id,
        )
        .order_by(LimitPolicyRulePartition.position.asc(), LimitPolicyRulePartition.id.asc())
    )
    return list(result)


async def delete_limit_policy_rule_partitions(
    *, org_id: UUID, rule_id: UUID, db: AsyncSession
) -> None:
    await db.execute(
        delete(LimitPolicyRulePartition).where(
            LimitPolicyRulePartition.org_id == org_id,
            LimitPolicyRulePartition.rule_id == rule_id,
        )
    )

