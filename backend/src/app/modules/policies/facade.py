from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.policies.internal import service
from app.modules.policies.schemas import (
    AccessPolicyOptionsResponse,
    AccessPolicyResponse,
    CreateAccessPolicyRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    CreateScopedPolicyAssignmentRequest,
    LimitPolicyResponse,
    LimitPolicyRuleResponse,
    PolicyAssignmentResponse,
    PolicyImpactResponse,
    ScopedPolicyAssignmentResponse,
    UpdateAccessPolicyRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)


async def list_access_policies(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[AccessPolicyResponse]:
    return await service.list_access_policies(scope=scope, db=db, actor=actor)


async def get_access_policy(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    return await service.get_access_policy(
        policy_id=policy_id, scope=scope, db=db, actor=actor
    )


async def create_access_policy(
    *,
    payload: CreateAccessPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    return await service.create_access_policy(payload=payload, scope=scope, db=db, actor=actor)


async def update_access_policy(
    *,
    policy_id: UUID,
    payload: UpdateAccessPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    return await service.update_access_policy(
        policy_id=policy_id, payload=payload, scope=scope, db=db, actor=actor
    )


async def delete_access_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    await service.delete_access_policy(policy_id=policy_id, scope=scope, db=db, actor=actor)


async def get_access_policy_impact(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    return await service.get_access_policy_impact(
        policy_id=policy_id, scope=scope, db=db, actor=actor
    )


async def get_access_policy_options(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    exclude_policy_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyOptionsResponse:
    return await service.get_access_policy_options(
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        exclude_policy_id=exclude_policy_id,
        scope=scope,
        db=db,
    )


async def list_limit_policies(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[LimitPolicyResponse]:
    return await service.list_limit_policies(scope=scope, db=db, actor=actor)


async def get_limit_policy(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    return await service.get_limit_policy(
        policy_id=policy_id, scope=scope, db=db, actor=actor
    )


async def create_limit_policy(
    *,
    payload: CreateLimitPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    return await service.create_limit_policy(payload=payload, scope=scope, db=db, actor=actor)


async def update_limit_policy(
    *,
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    return await service.update_limit_policy(
        policy_id=policy_id, payload=payload, scope=scope, db=db, actor=actor
    )


async def delete_limit_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    await service.delete_limit_policy(policy_id=policy_id, scope=scope, db=db, actor=actor)


async def create_limit_policy_rule(
    *,
    policy_id: UUID,
    payload: CreateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyRuleResponse:
    return await service.create_limit_policy_rule(
        policy_id=policy_id, payload=payload, scope=scope, db=db, actor=actor
    )


async def update_limit_policy_rule(
    *,
    rule_id: UUID,
    payload: UpdateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyRuleResponse:
    return await service.update_limit_policy_rule(
        rule_id=rule_id, payload=payload, scope=scope, db=db, actor=actor
    )


async def delete_limit_policy_rule(
    *, rule_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    await service.delete_limit_policy_rule(rule_id=rule_id, scope=scope, db=db, actor=actor)


async def get_limit_policy_impact(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    return await service.get_limit_policy_impact(
        policy_id=policy_id, scope=scope, db=db, actor=actor
    )


async def get_limit_policy_rule_impact(
    *,
    rule_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    return await service.get_limit_policy_rule_impact(
        rule_id=rule_id, scope=scope, db=db, actor=actor
    )


async def list_policy_assignments(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[PolicyAssignmentResponse]:
    return await service.list_policy_assignments(scope=scope, db=db, actor=actor)


async def create_policy_assignment(
    *,
    payload: CreatePolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyAssignmentResponse:
    return await service.create_policy_assignment(payload=payload, scope=scope, db=db, actor=actor)


async def create_scoped_policy_assignment(
    *,
    payload: CreateScopedPolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser,
) -> ScopedPolicyAssignmentResponse:
    return await service.create_scoped_policy_assignment(
        payload=payload, scope=scope, db=db, actor=actor
    )


async def update_policy_assignment(
    *,
    assignment_id: UUID,
    payload: UpdatePolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyAssignmentResponse:
    return await service.update_policy_assignment(
        assignment_id=assignment_id, payload=payload, scope=scope, db=db, actor=actor
    )


async def delete_policy_assignment(
    *, assignment_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    await service.delete_policy_assignment(
        assignment_id=assignment_id, scope=scope, db=db, actor=actor
    )
