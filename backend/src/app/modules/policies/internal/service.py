from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_facade
from app.modules.policies.errors import (
    PolicyAssignmentConflictError,
    PolicyNotFoundError,
    PolicyPermissionError,
    PolicyValidationError,
)
from app.modules.policies.internal import repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.policies.schemas import (
    AccessPolicyModelOption,
    AccessPolicyOptionsResponse,
    AccessPolicyPoolOption,
    AccessPolicyProviderOption,
    AccessPolicyPublicModelInput,
    AccessPolicyPublicModelResponse,
    AccessPolicyResponse,
    AccessPolicyRouteCandidateInput,
    AccessPolicyRouteCandidateResponse,
    CreateAccessPolicyRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    CreateScopedPolicyAssignmentRequest,
    LimitPolicyResponse,
    LimitPolicyRuleInput,
    LimitPolicyRuleMatcherInput,
    LimitPolicyRuleMatcherResponse,
    LimitPolicyRulePartitionInput,
    LimitPolicyRulePartitionResponse,
    LimitPolicyRuleResponse,
    PolicyAssignmentResponse,
    PolicyImpactResponse,
    PolicyImpactTarget,
    PolicyImpactVirtualKey,
    ScopedPolicyAssignmentResponse,
    UpdateAccessPolicyRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)
from app.modules.policies.validation import (
    FALLBACKABLE_PROVIDER_REASONS,
    EffectiveAccessPolicyCandidate,
    EffectiveAccessPolicyPublicModel,
    fallback_on_values,
    validate_access_policy_public_model_payload,
    validate_limit_rule_payload,
    validate_scoped_access_policy_public_model_payload,
)
from app.modules.policy_kernel import (
    assignment_scope_target_key,
    create_initial_active_revision,
    create_next_active_revision,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import PolicyAssignment, PolicyRevision
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.workspace_access import ScopeNotFoundError, WorkspaceAccessService

_FALLBACKABLE_PROVIDER_REASONS = FALLBACKABLE_PROVIDER_REASONS
_workspace_access = WorkspaceAccessService()


async def list_access_policies(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[AccessPolicyResponse]:
    policies = await repository.list_access_policies(org_id=scope.org_id, db=db)
    return [
        await _access_policy_response(policy=policy, scope=scope, db=db)
        for policy in policies
        if await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db)
    ]


async def get_access_policy(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    if not await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db):
        raise PolicyNotFoundError
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def create_access_policy(
    *,
    payload: CreateAccessPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    await _validate_access_policy_public_models(payload.public_models, scope=scope, db=db)
    async with transaction(db):
        shared_policy = await policy_kernel_repository.create_policy(
            org_id=scope.org_id,
            kind="access",
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            db=db,
        )
        revision = await create_initial_active_revision(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            created_by=actor.id if actor else None,
            db=db,
        )
        policy = await repository.create_access_policy(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            db=db,
        )
        for public_model in payload.public_models:
            await _create_public_model_from_input(
                policy_id=policy.id,
                policy_revision_id=revision.id,
                public_model=public_model,
                scope=scope,
                db=db,
            )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="access_policy.created",
            message=f"Created access policy {policy.name}.",
            metadata={"access_policy_id": str(policy.id)},
            db=db,
        )
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def update_access_policy(
    *,
    policy_id: UUID,
    payload: UpdateAccessPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> AccessPolicyResponse:
    if payload.public_models is not None:
        validate_access_policy_public_model_payload(payload.public_models)
    async with transaction(db):
        policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        if payload.public_models is not None:
            await _validate_access_policy_public_models(payload.public_models, scope=scope, db=db)
            await _validate_update_public_model_assignment_conflicts(
                policy_id=policy.id,
                public_models=payload.public_models,
                scope=scope,
                db=db,
            )
            if policy.owning_scope_type:
                await _validate_scoped_access_policy_narrowing(
                    public_models=payload.public_models,
                    scope_type=policy.owning_scope_type,
                    team_id=policy.owning_team_id,
                    project_id=policy.owning_project_id,
                    virtual_key_id=policy.owning_virtual_key_id,
                    exclude_policy_id=policy.id,
                    scope=scope,
                    db=db,
                )
        if payload.name is not None:
            policy.name = payload.name
        if "description" in payload.model_fields_set:
            policy.description = payload.description
        if payload.is_active is not None:
            policy.is_active = payload.is_active
        shared_policy = (
            await policy_kernel_repository.get_policy(
                org_id=scope.org_id, policy_id=policy.policy_id, db=db
            )
        )
        if shared_policy is not None:
            if payload.name is not None:
                shared_policy.name = payload.name
            if "description" in payload.model_fields_set:
                shared_policy.description = payload.description
            if payload.is_active is not None:
                shared_policy.is_active = payload.is_active
        if payload.public_models is not None:
            await repository.delete_access_policy_public_models(
                org_id=scope.org_id,
                access_policy_id=policy.id,
                db=db,
            )
            revision = await _publish_access_policy_revision(
                policy=policy,
                scope=scope,
                db=db,
                actor=actor,
            )
            for public_model in payload.public_models:
                await _create_public_model_from_input(
                    policy_id=policy.id,
                    policy_revision_id=revision.id,
                    public_model=public_model,
                    scope=scope,
                    db=db,
                )
        await db.flush()
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="access_policy.updated",
            message=f"Updated access policy {policy.name}.",
            metadata={
                "access_policy_id": str(policy.id),
                "changed_fields": sorted(payload.model_fields_set),
            },
            db=db,
        )
    return await _access_policy_response(policy=policy, scope=scope, db=db)


async def delete_access_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    async with transaction(db):
        policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        now = datetime.now(UTC)
        await policy_kernel_repository.close_assignments_for_policy(
            org_id=scope.org_id, policy_id=policy.policy_id, closed_at=now, db=db
        )
        policy.is_active = False
        policy.updated_at = now
        if policy.policy_id is not None:
            shared_policy = await policy_kernel_repository.get_policy(
                org_id=scope.org_id,
                policy_id=policy.policy_id,
                db=db,
            )
            if shared_policy is not None:
                shared_policy.is_active = False
                shared_policy.updated_at = now
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="access_policy.deleted",
            message=f"Deleted access policy {policy.name}.",
            metadata={"access_policy_id": str(policy.id)},
            db=db,
        )


async def list_limit_policies(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[LimitPolicyResponse]:
    policies = await repository.list_limit_policies(org_id=scope.org_id, db=db)
    return [
        await _limit_policy_response(policy=policy, scope=scope, db=db)
        for policy in policies
        if await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db)
    ]


async def get_limit_policy(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    if not await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db):
        raise PolicyNotFoundError
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def create_limit_policy(
    *,
    payload: CreateLimitPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    for rule in payload.rules:
        await _validate_limit_rule_filters(payload=rule, scope=scope, db=db)
    async with transaction(db):
        shared_policy = await policy_kernel_repository.create_policy(
            org_id=scope.org_id,
            kind="limit",
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            db=db,
        )
        revision = await create_initial_active_revision(
            org_id=scope.org_id,
            policy_id=shared_policy.id,
            created_by=actor.id if actor else None,
            db=db,
        )
        policy = await repository.create_limit_policy(
            org_id=scope.org_id,
            values=payload.model_dump(exclude={"rules"}),
            policy_id=shared_policy.id,
            db=db,
        )
        for rule in payload.rules:
            created_rule = await repository.create_limit_policy_rule(
                org_id=scope.org_id,
                limit_policy_id=policy.id,
                values=rule.model_dump(exclude={"matchers", "partitions"}),
                policy_revision_id=revision.id,
                db=db,
            )
            await _replace_limit_rule_matchers_and_partitions(
                payload=rule,
                rule_id=created_rule.id,
                matchers=rule.matchers,
                partitions=rule.partitions,
                scope=scope,
                db=db,
            )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_policy.created",
            message=f"Created limit policy {policy.name}.",
            metadata={"limit_policy_id": str(policy.id)},
            db=db,
        )
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def update_limit_policy(
    *,
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyResponse:
    values = payload.model_dump(exclude_unset=True)
    async with transaction(db):
        policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        for field, value in values.items():
            setattr(policy, field, value)
        shared_policy = (
            await policy_kernel_repository.get_policy(
                org_id=scope.org_id, policy_id=policy.policy_id, db=db
            )
        )
        if shared_policy is not None:
            if payload.name is not None:
                shared_policy.name = payload.name
            if "description" in payload.model_fields_set:
                shared_policy.description = payload.description
            if payload.is_active is not None:
                shared_policy.is_active = payload.is_active
        await db.flush()
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_policy.updated",
            message=f"Updated limit policy {policy.name}.",
            metadata={
                "limit_policy_id": str(policy.id),
                "changed_fields": sorted(payload.model_fields_set),
            },
            db=db,
        )
    return await _limit_policy_response(policy=policy, scope=scope, db=db)


async def create_limit_policy_rule(
    *,
    policy_id: UUID,
    payload: CreateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyRuleResponse:
    await _validate_limit_rule_filters(payload=payload, scope=scope, db=db)
    async with transaction(db):
        policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        revision, _copied_rules_by_source_id = await _create_next_limit_policy_revision(
            policy=policy,
            scope=scope,
            db=db,
            actor=actor,
        )
        rule = await repository.create_limit_policy_rule(
            org_id=scope.org_id,
            limit_policy_id=policy_id,
            values=payload.model_dump(exclude={"matchers", "partitions"}),
            policy_revision_id=revision.id,
            db=db,
        )
        await _replace_limit_rule_matchers_and_partitions(
            payload=payload,
            rule_id=rule.id,
            matchers=payload.matchers,
            partitions=payload.partitions,
            scope=scope,
            db=db,
        )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_rule.created",
            message=f"Created limit policy rule {rule.name}.",
            metadata={
                "limit_policy_id": str(policy_id),
                "limit_policy_rule_id": str(rule.id),
            },
            db=db,
        )
    return await _limit_policy_rule_response(rule=rule, scope=scope, db=db)


async def update_limit_policy_rule(
    *,
    rule_id: UUID,
    payload: UpdateLimitPolicyRuleRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> LimitPolicyRuleResponse:
    values = payload.model_dump(exclude_unset=True)
    async with transaction(db):
        rule = await _get_limit_policy_rule_or_raise(rule_id=rule_id, scope=scope, db=db)
        policy = await _get_limit_policy_or_raise(
            policy_id=rule.limit_policy_id, scope=scope, db=db
        )
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        candidate = LimitPolicyRuleInput(
            name=values.get("name", rule.name),
            limit_type=values.get("limit_type", rule.limit_type),
            limit_value=values.get("limit_value", rule.limit_value),
            interval_unit=values.get("interval_unit", rule.interval_unit),
            interval_count=values.get("interval_count", rule.interval_count),
            provider_id=values.get("provider_id", rule.provider_id),
            credential_pool_id=values.get("credential_pool_id", rule.credential_pool_id),
            model_offering_id=values.get("model_offering_id", rule.model_offering_id),
            access_policy_id=values.get("access_policy_id", rule.access_policy_id),
            matchers=(
                payload.matchers
                if payload.matchers is not None
                else await _limit_rule_matcher_inputs(rule_id=rule.id, scope=scope, db=db)
            ),
            partitions=(
                payload.partitions
                if payload.partitions is not None
                else await _limit_rule_partition_inputs(rule_id=rule.id, scope=scope, db=db)
            ),
            is_active=values.get("is_active", rule.is_active),
        )
        await _validate_limit_rule_filters(payload=candidate, scope=scope, db=db)
        revision, copied_rules_by_source_id = await _create_next_limit_policy_revision(
            policy=policy,
            scope=scope,
            db=db,
            actor=actor,
        )
        updated_rule = copied_rules_by_source_id.get(rule.id)
        if updated_rule is None:
            raise PolicyValidationError
        for field, value in candidate.model_dump(exclude={"matchers", "partitions"}).items():
            setattr(updated_rule, field, value)
        await _replace_limit_rule_matchers_and_partitions(
            payload=candidate,
            rule_id=updated_rule.id,
            matchers=candidate.matchers,
            partitions=candidate.partitions,
            scope=scope,
            db=db,
        )
        await db.flush()
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_rule.updated",
            message=f"Updated limit policy rule {rule.name}.",
            metadata={
                "limit_policy_id": str(rule.limit_policy_id),
                "limit_policy_rule_id": str(updated_rule.id),
                "changed_fields": sorted(payload.model_fields_set),
            },
            db=db,
        )
    return await _limit_policy_rule_response(rule=updated_rule, scope=scope, db=db)


async def delete_limit_policy_rule(
    *, rule_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    async with transaction(db):
        rule = await _get_limit_policy_rule_or_raise(rule_id=rule_id, scope=scope, db=db)
        policy = await _get_limit_policy_or_raise(
            policy_id=rule.limit_policy_id, scope=scope, db=db
        )
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        _revision, copied_rules_by_source_id = await _create_next_limit_policy_revision(
            policy=policy,
            scope=scope,
            db=db,
            actor=actor,
        )
        copied_rule = copied_rules_by_source_id.get(rule.id)
        if copied_rule is None:
            raise PolicyValidationError
        await db.delete(copied_rule)
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_rule.deleted",
            message=f"Deleted limit policy rule {rule.name}.",
            metadata={
                "limit_policy_id": str(rule.limit_policy_id),
                "limit_policy_rule_id": str(rule.id),
            },
            db=db,
        )


async def delete_limit_policy(
    *, policy_id: UUID, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> None:
    async with transaction(db):
        policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        if not await _can_manage_policy_definition(policy=policy, actor=actor, scope=scope, db=db):
            raise PolicyPermissionError
        now = datetime.now(UTC)
        await policy_kernel_repository.close_assignments_for_policy(
            org_id=scope.org_id, policy_id=policy.policy_id, closed_at=now, db=db
        )
        policy.is_active = False
        policy.updated_at = now
        if policy.policy_id is not None:
            shared_policy = await policy_kernel_repository.get_policy(
                org_id=scope.org_id,
                policy_id=policy.policy_id,
                db=db,
            )
            if shared_policy is not None:
                shared_policy.is_active = False
                shared_policy.updated_at = now
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="limit_policy.deleted",
            message=f"Deleted limit policy {policy.name}.",
            metadata={"limit_policy_id": str(policy.id)},
            db=db,
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
    parent_public_models = await _parent_access_public_model_options(
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        exclude_policy_id=exclude_policy_id,
        scope=scope,
        db=db,
    )
    if parent_public_models:
        return await _options_from_public_models(
            public_models=parent_public_models,
            scope=scope,
            db=db,
        )
    return await _all_access_options(scope=scope, db=db)


async def list_policy_assignments(
    *, scope: Scope, db: AsyncSession, actor: AuthenticatedUser | None = None
) -> list[PolicyAssignmentResponse]:
    assignments = await policy_kernel_repository.list_policy_assignments(
        org_id=scope.org_id, db=db
    )
    visible = [
        assignment
        for assignment in assignments
        if await _can_view_assignment(assignment=assignment, actor=actor, scope=scope, db=db)
    ]
    return [PolicyAssignmentResponse.model_validate(assignment) for assignment in visible]


async def create_policy_assignment(
    *,
    payload: CreatePolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyAssignmentResponse:
    team_id, project_id, virtual_key_id = await _validate_assignment_target(
        scope_type=payload.scope_type,
        team_id=payload.team_id,
        project_id=payload.project_id,
        virtual_key_id=payload.virtual_key_id,
        scope=scope,
        db=db,
    )
    normalized_payload = payload.model_copy(
        update={
            "team_id": team_id,
            "project_id": project_id,
            "virtual_key_id": virtual_key_id,
        }
    )
    policy = await _validate_assignment_policy(payload=normalized_payload, scope=scope, db=db)
    shared_policy_id = _assignment_shared_policy_id(policy)
    scope_target_key = _assignment_scope_target_key(
        scope_type=normalized_payload.scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    async with transaction(db):
        existing = await policy_kernel_repository.find_active_policy_assignment_for_scope(
            org_id=scope.org_id,
            policy_id=shared_policy_id,
            policy_type=normalized_payload.policy_type,
            scope_type=normalized_payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
        if existing is not None and payload.is_active:
            raise PolicyAssignmentConflictError
        if normalized_payload.policy_type == "access" and normalized_payload.is_active:
            await _validate_no_same_scope_public_model_conflicts(
                payload=normalized_payload,
                access_policy_id=policy.id,
                scope=scope,
                db=db,
            )
        values = normalized_payload.model_dump()
        values.update(
            {
                "policy_id": shared_policy_id,
                "team_id": team_id,
                "project_id": project_id,
                "virtual_key_id": virtual_key_id,
                "scope_target_key": scope_target_key,
                "effective_from": datetime.now(UTC),
                "effective_to": None if normalized_payload.is_active else datetime.now(UTC),
            }
        )
        assignment = await policy_kernel_repository.create_policy_assignment(
            org_id=scope.org_id,
            values=values,
            db=db,
        )
        activity_team_id, activity_project_id = await _assignment_activity_scope_ids(
            scope=scope, assignment=assignment, db=db
        )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="policy_assignment.created",
            message="Created policy assignment.",
            team_id=activity_team_id,
            project_id=activity_project_id,
            virtual_key_id=assignment.virtual_key_id,
            metadata=_assignment_metadata(assignment),
            db=db,
        )
    return PolicyAssignmentResponse.model_validate(assignment)


async def create_scoped_policy_assignment(
    *,
    payload: CreateScopedPolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser,
) -> ScopedPolicyAssignmentResponse:
    team_id, project_id, virtual_key_id = await _validate_assignment_target(
        scope_type=payload.scope_type,
        team_id=payload.team_id,
        project_id=payload.project_id,
        virtual_key_id=payload.virtual_key_id,
        scope=scope,
        db=db,
    )
    if payload.policy_type == "access":
        assert payload.access_policy is not None
        await _validate_access_policy_public_models(
            payload.access_policy.public_models,
            scope=scope,
            db=db,
        )
        await _validate_scoped_access_policy_narrowing(
            public_models=payload.access_policy.public_models,
            scope_type=payload.scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            scope=scope,
            db=db,
        )
    else:
        assert payload.limit_policy is not None
        for rule in payload.limit_policy.rules:
            await _validate_limit_rule_filters(payload=rule, scope=scope, db=db)
    async with transaction(db):
        if payload.policy_type == "access":
            assert payload.access_policy is not None
            shared_policy = await policy_kernel_repository.create_policy(
                org_id=scope.org_id,
                kind="access",
                name=payload.access_policy.name,
                description=payload.access_policy.description,
                is_active=payload.access_policy.is_active,
                db=db,
            )
            revision = await create_initial_active_revision(
                org_id=scope.org_id,
                policy_id=shared_policy.id,
                created_by=actor.id,
                db=db,
            )
            access_policy = await repository.create_access_policy(
                org_id=scope.org_id,
                policy_id=shared_policy.id,
                name=payload.access_policy.name,
                description=payload.access_policy.description,
                is_active=payload.access_policy.is_active,
                owning_scope_type=payload.scope_type,
                owning_team_id=team_id,
                owning_project_id=project_id,
                owning_virtual_key_id=virtual_key_id,
                db=db,
            )
            for public_model in payload.access_policy.public_models:
                await _create_public_model_from_input(
                    policy_id=access_policy.id,
                    policy_revision_id=revision.id,
                    public_model=public_model,
                    scope=scope,
                    db=db,
                )
            assignment_payload = CreatePolicyAssignmentRequest(
                policy_id=shared_policy.id,
                policy_type="access",
                scope_type=payload.scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                is_active=payload.is_active,
            )
            policy_response = await _access_policy_response(
                policy=access_policy, scope=scope, db=db
            )
            limit_response = None
        else:
            assert payload.limit_policy is not None
            shared_policy = await policy_kernel_repository.create_policy(
                org_id=scope.org_id,
                kind="limit",
                name=payload.limit_policy.name,
                description=payload.limit_policy.description,
                is_active=payload.limit_policy.is_active,
                db=db,
            )
            revision = await create_initial_active_revision(
                org_id=scope.org_id,
                policy_id=shared_policy.id,
                created_by=actor.id,
                db=db,
            )
            limit_policy = await repository.create_limit_policy(
                org_id=scope.org_id,
                values={
                    **payload.limit_policy.model_dump(exclude={"rules"}),
                    "owning_scope_type": payload.scope_type,
                    "owning_team_id": team_id,
                    "owning_project_id": project_id,
                    "owning_virtual_key_id": virtual_key_id,
                },
                policy_id=shared_policy.id,
                db=db,
            )
            for rule in payload.limit_policy.rules:
                created_rule = await repository.create_limit_policy_rule(
                    org_id=scope.org_id,
                    limit_policy_id=limit_policy.id,
                    values=rule.model_dump(exclude={"matchers", "partitions"}),
                    policy_revision_id=revision.id,
                    db=db,
                )
                await _replace_limit_rule_matchers_and_partitions(
                    payload=rule,
                    rule_id=created_rule.id,
                    matchers=rule.matchers,
                    partitions=rule.partitions,
                    scope=scope,
                    db=db,
                )
            assignment_payload = CreatePolicyAssignmentRequest(
                policy_id=shared_policy.id,
                policy_type="limit",
                scope_type=payload.scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                is_active=payload.is_active,
            )
            policy_response = None
            limit_response = await _limit_policy_response(policy=limit_policy, scope=scope, db=db)
        assignment_policy = await _validate_assignment_policy(
            payload=assignment_payload, scope=scope, db=db
        )
        assignment_payload = assignment_payload.model_copy(
            update={
                "policy_id": assignment_policy.policy_id,
            }
        )
        if assignment_payload.policy_type == "access" and assignment_payload.is_active:
            await _validate_no_same_scope_public_model_conflicts(
                payload=assignment_payload,
                access_policy_id=assignment_policy.id,
                scope=scope,
                db=db,
            )
        now = datetime.now(UTC)
        assignment = await policy_kernel_repository.create_policy_assignment(
            org_id=scope.org_id,
            values={
                **assignment_payload.model_dump(),
                "policy_id": _assignment_shared_policy_id(assignment_policy),
                "scope_target_key": _assignment_scope_target_key(
                    scope_type=assignment_payload.scope_type,
                    team_id=team_id,
                    project_id=project_id,
                    virtual_key_id=virtual_key_id,
                ),
                "effective_from": now,
                "effective_to": None if assignment_payload.is_active else now,
            },
            db=db,
        )
        activity_team_id, activity_project_id = await _assignment_activity_scope_ids(
            scope=scope, assignment=assignment, db=db
        )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="policy_assignment.created",
            message="Created scoped policy assignment.",
            team_id=activity_team_id,
            project_id=activity_project_id,
            virtual_key_id=assignment.virtual_key_id,
            metadata=_assignment_metadata(assignment),
            db=db,
        )
    return ScopedPolicyAssignmentResponse(
        policy_type=payload.policy_type,
        access_policy=policy_response,
        limit_policy=limit_response,
        assignment=PolicyAssignmentResponse.model_validate(assignment),
    )


async def update_policy_assignment(
    *,
    assignment_id: UUID,
    payload: UpdatePolicyAssignmentRequest,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyAssignmentResponse:
    async with transaction(db):
        assignment = await _get_policy_assignment_or_raise(
            assignment_id=assignment_id, scope=scope, db=db
        )
        if payload.is_active is not None:
            now = datetime.now(UTC)
            if payload.is_active and not assignment.is_active:
                duplicate = await policy_kernel_repository.find_active_policy_assignment_for_scope(
                    org_id=scope.org_id,
                    policy_id=assignment.policy_id,
                    policy_type=assignment.policy_type,
                    scope_type=assignment.scope_type,
                    team_id=assignment.team_id,
                    project_id=assignment.project_id,
                    virtual_key_id=assignment.virtual_key_id,
                    db=db,
                )
                if duplicate is not None and duplicate.id != assignment.id:
                    raise PolicyAssignmentConflictError
                if assignment.policy_type == "access":
                    access_policy = await repository.get_access_policy_by_shared_policy(
                        shared_policy_id=assignment.policy_id,
                        org_id=scope.org_id,
                        db=db,
                    )
                    if access_policy is None:
                        raise PolicyValidationError
                    await _validate_no_same_scope_public_model_conflicts(
                        payload=CreatePolicyAssignmentRequest(
                            policy_id=assignment.policy_id,
                            policy_type="access",
                            scope_type=assignment.scope_type,
                            team_id=assignment.team_id,
                            project_id=assignment.project_id,
                            virtual_key_id=assignment.virtual_key_id,
                            is_active=True,
                        ),
                        access_policy_id=access_policy.id,
                        scope=scope,
                        db=db,
                    )
                assignment.effective_to = assignment.effective_to or now
                replacement = await policy_kernel_repository.create_policy_assignment(
                    org_id=scope.org_id,
                    values={
                        "policy_id": assignment.policy_id,
                        "policy_type": assignment.policy_type,
                        "scope_type": assignment.scope_type,
                        "team_id": assignment.team_id,
                        "project_id": assignment.project_id,
                        "virtual_key_id": assignment.virtual_key_id,
                        "scope_target_key": assignment.scope_target_key,
                        "mode": assignment.mode,
                        "effective_from": now,
                        "effective_to": None,
                        "is_active": True,
                    },
                    db=db,
                )
                assignment.superseded_by_assignment_id = replacement.id
                assignment = replacement
            elif not payload.is_active and assignment.is_active:
                assignment.is_active = False
                assignment.effective_to = assignment.effective_to or now
        await db.flush()
        activity_team_id, activity_project_id = await _assignment_activity_scope_ids(
            scope=scope, assignment=assignment, db=db
        )
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="policy_assignment.updated",
            message="Updated policy assignment.",
            team_id=activity_team_id,
            project_id=activity_project_id,
            virtual_key_id=assignment.virtual_key_id,
            metadata={
                **_assignment_metadata(assignment),
                "changed_fields": sorted(payload.model_fields_set),
            },
            db=db,
        )
    return PolicyAssignmentResponse.model_validate(assignment)


async def delete_policy_assignment(
    *,
    assignment_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> None:
    async with transaction(db):
        assignment = await _get_policy_assignment_or_raise(
            assignment_id=assignment_id, scope=scope, db=db
        )
        team_id, project_id = await _assignment_activity_scope_ids(
            scope=scope, assignment=assignment, db=db
        )
        virtual_key_id = assignment.virtual_key_id
        assignment.is_active = False
        assignment.effective_to = assignment.effective_to or datetime.now(UTC)
        await _record_policy_activity(
            actor=actor,
            scope=scope,
            action="policy_assignment.deleted",
            message="Deleted policy assignment.",
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            metadata=_assignment_metadata(assignment),
            db=db,
        )


async def get_access_policy_impact(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    if not await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db):
        raise PolicyNotFoundError
    assignments = await policy_kernel_repository.list_policy_assignments_for_policy(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        active_only=True,
        db=db,
    )
    return await _policy_impact_from_assignments(
        assignments=assignments,
        scope=scope,
        db=db,
        exclude_access_policy_id=policy_id,
    )


async def get_limit_policy_impact(
    *,
    policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    policy = await _get_limit_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    if not await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db):
        raise PolicyNotFoundError
    assignments = await policy_kernel_repository.list_policy_assignments_for_policy(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        active_only=True,
        db=db,
    )
    return await _policy_impact_from_assignments(
        assignments=assignments,
        scope=scope,
        db=db,
    )


async def get_limit_policy_rule_impact(
    *,
    rule_id: UUID,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None = None,
) -> PolicyImpactResponse:
    rule = await _get_limit_policy_rule_or_raise(rule_id=rule_id, scope=scope, db=db)
    policy = await _get_limit_policy_or_raise(policy_id=rule.limit_policy_id, scope=scope, db=db)
    if not await _can_view_policy(policy=policy, actor=actor, scope=scope, db=db):
        raise PolicyNotFoundError
    assignments = await policy_kernel_repository.list_policy_assignments_for_policy(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        active_only=True,
        db=db,
    )
    return await _policy_impact_from_assignments(
        assignments=assignments,
        scope=scope,
        db=db,
    )


async def _access_policy_response(
    *, policy: AccessPolicy, scope: Scope, db: AsyncSession
) -> AccessPolicyResponse:
    public_models = await repository.list_access_policy_public_models(
        org_id=scope.org_id, access_policy_id=policy.id, db=db
    )
    response = AccessPolicyResponse.model_validate(policy)
    response.public_models = [
        await _public_model_response(public_model=public_model, scope=scope, db=db)
        for public_model in public_models
    ]
    return response


async def _public_model_response(
    *, public_model: AccessPolicyPublicModel, scope: Scope, db: AsyncSession
) -> AccessPolicyPublicModelResponse:
    candidates = await repository.list_access_policy_route_candidates(
        org_id=scope.org_id,
        public_model_id=public_model.id,
        db=db,
    )
    response = AccessPolicyPublicModelResponse.model_validate(public_model)
    response.candidates = [
        AccessPolicyRouteCandidateResponse.model_validate(candidate) for candidate in candidates
    ]
    return response


async def _limit_policy_response(
    *, policy: LimitPolicy, scope: Scope, db: AsyncSession
) -> LimitPolicyResponse:
    rules = await repository.list_limit_policy_rules(
        org_id=scope.org_id, limit_policy_id=policy.id, db=db
    )
    response = LimitPolicyResponse.model_validate(policy)
    response.rules = [
        await _limit_policy_rule_response(rule=rule, scope=scope, db=db) for rule in rules
    ]
    return response


async def _limit_policy_rule_response(
    *, rule: LimitPolicyRule, scope: Scope, db: AsyncSession
) -> LimitPolicyRuleResponse:
    response = LimitPolicyRuleResponse.model_validate(rule)
    response.matchers = [
        LimitPolicyRuleMatcherResponse.model_validate(matcher)
        for matcher in await repository.list_limit_policy_rule_matchers(
            org_id=scope.org_id,
            rule_id=rule.id,
            db=db,
        )
    ]
    response.partitions = [
        LimitPolicyRulePartitionResponse.model_validate(partition)
        for partition in await repository.list_limit_policy_rule_partitions(
            org_id=scope.org_id,
            rule_id=rule.id,
            db=db,
        )
    ]
    return response


async def _limit_rule_matcher_inputs(
    *, rule_id: UUID, scope: Scope, db: AsyncSession
) -> list[LimitPolicyRuleMatcherInput]:
    return [
        LimitPolicyRuleMatcherInput(
            dimension=matcher.dimension,
            operator=matcher.operator,
            value_json=matcher.value_json,
        )
        for matcher in await repository.list_limit_policy_rule_matchers(
            org_id=scope.org_id,
            rule_id=rule_id,
            db=db,
        )
    ]


async def _limit_rule_partition_inputs(
    *, rule_id: UUID, scope: Scope, db: AsyncSession
) -> list[LimitPolicyRulePartitionInput]:
    return [
        LimitPolicyRulePartitionInput(
            dimension=partition.dimension,
            position=partition.position,
        )
        for partition in await repository.list_limit_policy_rule_partitions(
            org_id=scope.org_id,
            rule_id=rule_id,
            db=db,
        )
    ]


async def _replace_limit_rule_matchers_and_partitions(
    *,
    payload: LimitPolicyRuleInput,
    rule_id: UUID,
    matchers: list[LimitPolicyRuleMatcherInput],
    partitions: list[LimitPolicyRulePartitionInput],
    scope: Scope,
    db: AsyncSession,
) -> None:
    await repository.delete_limit_policy_rule_matchers(
        org_id=scope.org_id,
        rule_id=rule_id,
        db=db,
    )
    await repository.delete_limit_policy_rule_partitions(
        org_id=scope.org_id,
        rule_id=rule_id,
        db=db,
    )
    for matcher in _legacy_limit_filter_matchers(payload=payload, matchers=matchers):
        await repository.create_limit_policy_rule_matcher(
            org_id=scope.org_id,
            rule_id=rule_id,
            dimension=matcher.dimension,
            operator=matcher.operator,
            value_json=matcher.value_json,
            db=db,
        )
    for partition in sorted(partitions, key=lambda item: item.position):
        await repository.create_limit_policy_rule_partition(
            org_id=scope.org_id,
            rule_id=rule_id,
            dimension=partition.dimension,
            position=partition.position,
            db=db,
        )


def _legacy_limit_filter_matchers(
    *,
    payload: LimitPolicyRuleInput,
    matchers: list[LimitPolicyRuleMatcherInput],
) -> list[LimitPolicyRuleMatcherInput]:
    legacy_filters = (
        ("provider_id", payload.provider_id),
        ("credential_pool_id", payload.credential_pool_id),
        ("provider_model_offering_id", payload.model_offering_id),
        ("access_policy_id", payload.access_policy_id),
    )
    legacy_dimensions = {dimension for dimension, value in legacy_filters if value is not None}
    merged = [matcher for matcher in matchers if matcher.dimension not in legacy_dimensions]
    existing = {
        (matcher.dimension, matcher.operator, str(matcher.value_json)) for matcher in merged
    }
    for dimension, value in legacy_filters:
        if value is None:
            continue
        key = (dimension, "eq", str(value))
        if key in existing:
            continue
        merged.append(
            LimitPolicyRuleMatcherInput(
                dimension=dimension,
                operator="eq",
                value_json=str(value),
            )
        )
        existing.add(key)
    return merged


async def _get_access_policy_or_raise(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> AccessPolicy:
    policy = await repository.get_access_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise PolicyNotFoundError
    return policy


async def _get_limit_policy_or_raise(
    *, policy_id: UUID, scope: Scope, db: AsyncSession
) -> LimitPolicy:
    policy = await repository.get_limit_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise PolicyNotFoundError
    return policy


async def _get_limit_policy_rule_or_raise(
    *, rule_id: UUID, scope: Scope, db: AsyncSession
) -> LimitPolicyRule:
    rule = await repository.get_limit_policy_rule(rule_id=rule_id, org_id=scope.org_id, db=db)
    if rule is None:
        raise PolicyNotFoundError
    return rule


async def _active_limit_policy_revision(
    *, policy: LimitPolicy, scope: Scope, db: AsyncSession
) -> UUID | None:
    revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db,
    )
    return revision.id if revision else None


async def _create_next_limit_policy_revision(
    *,
    policy: LimitPolicy,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None,
) -> tuple[PolicyRevision, dict[UUID, LimitPolicyRule]]:
    now = datetime.now(UTC)
    active_revision = await policy_kernel_repository.get_active_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db,
    )
    latest_revision = await policy_kernel_repository.get_latest_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        db=db,
    )
    if active_revision is not None:
        active_revision.status = "archived"
        active_revision.archived_at = now
    revision = await policy_kernel_repository.create_policy_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        revision_number=(latest_revision.revision_number + 1 if latest_revision else 1),
        status="active",
        created_by=actor.id if actor else None,
        db=db,
    )
    revision.activated_at = now
    if active_revision is None:
        return revision, {}
    copied_rules_by_source_id: dict[UUID, LimitPolicyRule] = {}
    for old_rule in await repository.list_limit_policy_revision_rules(
        org_id=scope.org_id,
        limit_policy_id=policy.id,
        policy_revision_id=active_revision.id,
        db=db,
    ):
        copied_rule = await repository.create_limit_policy_rule(
            org_id=scope.org_id,
            limit_policy_id=policy.id,
            values={
                "name": old_rule.name,
                "limit_type": old_rule.limit_type,
                "limit_value": old_rule.limit_value,
                "interval_unit": old_rule.interval_unit,
                "interval_count": old_rule.interval_count,
                "provider_id": old_rule.provider_id,
                "credential_pool_id": old_rule.credential_pool_id,
                "model_offering_id": old_rule.model_offering_id,
                "access_policy_id": old_rule.access_policy_id,
                "is_active": old_rule.is_active,
            },
            policy_revision_id=revision.id,
            db=db,
        )
        await _copy_limit_rule_matchers_and_partitions(
            source_rule_id=old_rule.id,
            target_rule_id=copied_rule.id,
            scope=scope,
            db=db,
        )
        copied_rules_by_source_id[old_rule.id] = copied_rule
    return revision, copied_rules_by_source_id


async def _copy_limit_rule_matchers_and_partitions(
    *,
    source_rule_id: UUID,
    target_rule_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> None:
    for matcher in await repository.list_limit_policy_rule_matchers(
        org_id=scope.org_id,
        rule_id=source_rule_id,
        db=db,
    ):
        await repository.create_limit_policy_rule_matcher(
            org_id=scope.org_id,
            rule_id=target_rule_id,
            dimension=matcher.dimension,
            operator=matcher.operator,
            value_json=matcher.value_json,
            db=db,
        )
    for partition in await repository.list_limit_policy_rule_partitions(
        org_id=scope.org_id,
        rule_id=source_rule_id,
        db=db,
    ):
        await repository.create_limit_policy_rule_partition(
            org_id=scope.org_id,
            rule_id=target_rule_id,
            dimension=partition.dimension,
            position=partition.position,
            db=db,
        )


async def _get_policy_assignment_or_raise(
    *, assignment_id: UUID, scope: Scope, db: AsyncSession
) -> PolicyAssignment:
    assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=assignment_id, org_id=scope.org_id, db=db
    )
    if assignment is None:
        raise PolicyNotFoundError
    return assignment


async def _all_access_options(*, scope: Scope, db: AsyncSession) -> AccessPolicyOptionsResponse:
    providers = await providers_facade.list_providers(scope=scope, db=db)
    groups: dict[UUID, AccessPolicyProviderOption] = {}
    for provider in providers:
        if not provider.is_active:
            continue
        pools = await providers_facade.list_credential_pools(
            provider_id=provider.id,
            scope=scope,
            db=db,
        )
        models = await providers_facade.list_model_offerings(
            provider_id=provider.id,
            search=None,
            modalities=None,
            is_active=True,
            limit=1000,
            offset=0,
            scope=scope,
            db=db,
        )
        pool_options = [
            AccessPolicyPoolOption(
                id=pool.id,
                name=pool.name,
                models=[
                    AccessPolicyModelOption(
                        id=model.id,
                        provider_model_name=model.provider_model_name,
                    )
                    for model in models.items
                ],
            )
            for pool in pools
            if pool.is_active
            and await _pool_has_active_credential(
                provider_id=provider.id, pool_id=pool.id, scope=scope, db=db
            )
        ]
        if pool_options:
            groups[provider.id] = AccessPolicyProviderOption(
                id=provider.id,
                display_name=provider.display_name or provider.name,
                pools=pool_options,
            )
    return AccessPolicyOptionsResponse(providers=list(groups.values()))


async def _options_from_public_models(
    *,
    public_models: dict[str, "_EffectivePublicModel"],
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyOptionsResponse:
    providers: dict[UUID, AccessPolicyProviderOption] = {}
    pools: dict[tuple[UUID, UUID], AccessPolicyPoolOption] = {}
    seen_models: set[tuple[UUID, UUID, UUID]] = set()
    for public_model in public_models.values():
        for candidate in public_model.candidates:
            await _add_candidate_access_option(
                candidate=candidate,
                providers=providers,
                pools=pools,
                seen_models=seen_models,
                scope=scope,
                db=db,
            )
    return AccessPolicyOptionsResponse(providers=list(providers.values()))


async def _add_candidate_access_option(
    *,
    candidate: "_EffectivePublicModelCandidate",
    providers: dict[UUID, AccessPolicyProviderOption],
    pools: dict[tuple[UUID, UUID], AccessPolicyPoolOption],
    seen_models: set[tuple[UUID, UUID, UUID]],
    scope: Scope,
    db: AsyncSession,
) -> None:
    try:
        provider = await providers_facade.get_provider(
            provider_id=candidate.provider_id,
            scope=scope,
            db=db,
        )
        pool = await providers_facade.get_credential_pool(
            pool_id=candidate.credential_pool_id,
            scope=scope,
            db=db,
        )
        model = await providers_facade.get_model_offering(
            model_offering_id=candidate.model_id,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError:
        return
    if not await _is_routable_provider_pool_model(
        provider_id=candidate.provider_id,
        pool_id=candidate.credential_pool_id,
        model_id=candidate.model_id,
        scope=scope,
        db=db,
    ):
        return
    provider_option = providers.setdefault(
        provider.id,
        AccessPolicyProviderOption(
            id=provider.id,
            display_name=provider.display_name or provider.name,
            pools=[],
        ),
    )
    pool_key = (provider.id, pool.id)
    pool_option = pools.get(pool_key)
    if pool_option is None:
        pool_option = AccessPolicyPoolOption(id=pool.id, name=pool.name, models=[])
        pools[pool_key] = pool_option
        provider_option.pools.append(pool_option)
    model_key = (provider.id, pool.id, model.id)
    if model_key in seen_models:
        return
    seen_models.add(model_key)
    pool_option.models.append(
        AccessPolicyModelOption(
            id=model.id,
            provider_model_name=model.provider_model_name,
        )
    )


async def _validate_access_route_candidate(
    *, candidate: AccessPolicyRouteCandidateInput, scope: Scope, db: AsyncSession
) -> None:
    try:
        provider = await providers_facade.get_provider(
            provider_id=candidate.provider_id, scope=scope, db=db
        )
        pool = await providers_facade.get_credential_pool(
            pool_id=candidate.credential_pool_id, scope=scope, db=db
        )
        model = await providers_facade.get_model_offering(
            model_offering_id=candidate.model_offering_id, scope=scope, db=db
        )
        if not provider.is_active or not pool.is_active or pool.provider_id != provider.id:
            raise PolicyValidationError
        if not await _pool_has_active_credential(
            provider_id=provider.id, pool_id=pool.id, scope=scope, db=db
        ):
            raise PolicyValidationError
        if not model.is_active or model.provider_id != provider.id:
            raise PolicyValidationError
    except ProviderNotFoundError as exc:
        raise PolicyValidationError from exc


async def _validate_access_policy_public_models(
    public_models: list[AccessPolicyPublicModelInput],
    *,
    scope: Scope,
    db: AsyncSession,
) -> None:
    validate_access_policy_public_model_payload(public_models)
    for public_model in public_models:
        for candidate in public_model.candidates:
            await _validate_access_route_candidate(candidate=candidate, scope=scope, db=db)


async def _create_public_model_from_input(
    *,
    policy_id: UUID,
    policy_revision_id: UUID,
    public_model: AccessPolicyPublicModelInput,
    scope: Scope,
    db: AsyncSession,
) -> AccessPolicyPublicModel:
    created = await repository.create_access_policy_public_model(
        org_id=scope.org_id,
        access_policy_id=policy_id,
        public_model_name=public_model.public_model_name.strip(),
        routing_mode=public_model.routing_mode,
        fallback_on=_fallback_on_values(public_model),
        max_route_attempts=public_model.max_route_attempts,
        is_active=public_model.is_active,
        policy_revision_id=policy_revision_id,
        db=db,
    )
    for candidate in public_model.candidates:
        await repository.create_access_policy_route_candidate(
            org_id=scope.org_id,
            public_model_id=created.id,
            provider_id=candidate.provider_id,
            credential_pool_id=candidate.credential_pool_id,
            model_offering_id=candidate.model_offering_id,
            priority=candidate.priority,
            weight=candidate.weight,
            is_active=candidate.is_active,
            db=db,
        )
    return created


async def _publish_access_policy_revision(
    *,
    policy: AccessPolicy,
    scope: Scope,
    db: AsyncSession,
    actor: AuthenticatedUser | None,
) -> PolicyRevision:
    return await create_next_active_revision(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        created_by=actor.id if actor else None,
        db=db,
    )


def _fallback_on_values(public_model: AccessPolicyPublicModelInput) -> list[str]:
    return fallback_on_values(public_model)


def _assignment_applies_to_parent(
    *,
    assignment: PolicyAssignment,
    team_id: UUID | None,
    project_id: UUID | None,
) -> bool:
    if assignment.scope_type == "org":
        return True
    if assignment.scope_type == "team":
        return team_id is not None and assignment.team_id == team_id
    if assignment.scope_type == "project":
        return project_id is not None and assignment.project_id == project_id
    return False


async def _validate_scoped_access_policy_narrowing(
    *,
    public_models: list[AccessPolicyPublicModelInput],
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    exclude_policy_id: UUID | None = None,
    scope: Scope,
    db: AsyncSession,
) -> None:
    parent_public_models = await _parent_access_public_model_options(
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        exclude_policy_id=exclude_policy_id,
        scope=scope,
        db=db,
    )
    if not parent_public_models:
        return
    await _validate_scoped_access_policy_public_models(
        public_models=public_models,
        parent_public_models=parent_public_models,
        scope=scope,
        db=db,
    )


async def _parent_access_public_model_options(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    exclude_policy_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> dict[str, "_EffectivePublicModel"]:
    if scope_type == "org":
        return {}
    exclude_shared_policy_id: UUID | None = None
    if exclude_policy_id is not None:
        excluded_policy = await repository.get_access_policy(
            policy_id=exclude_policy_id,
            org_id=scope.org_id,
            db=db,
        )
        exclude_shared_policy_id = (
            excluded_policy.policy_id if excluded_policy else exclude_policy_id
        )
    parent_scopes = ["org"] if scope_type == "team" else ["org", "team"]
    if scope_type == "virtual_key":
        parent_scopes.append("project")
    resolved_team_id = team_id
    if project_id is not None:
        project = await keys_facade.get_project(project_id=project_id, scope=scope, db=db)
        resolved_team_id = project.team_id
    if virtual_key_id is not None:
        if project_id is None:
            virtual_key = await repository.get_virtual_key(
                org_id=scope.org_id, virtual_key_id=virtual_key_id, db=db
            )
            if virtual_key is None:
                raise PolicyNotFoundError
            project_id = virtual_key.project_id
        project = await keys_facade.get_project(project_id=project_id, scope=scope, db=db)
        resolved_team_id = project.team_id

    effective: dict[str, _EffectivePublicModel] | None = None
    for parent_scope in parent_scopes:
        assignments = await policy_kernel_repository.list_active_policy_assignments_for_scope(
            org_id=scope.org_id,
            scope_type=parent_scope,
            policy_type="access",
            db=db,
        )
        scoped = [
            assignment
            for assignment in assignments
            if assignment.policy_id != exclude_shared_policy_id
            and _assignment_applies_to_parent(
                assignment=assignment,
                team_id=resolved_team_id,
                project_id=project_id,
            )
        ]
        options = await _public_model_options_from_assignments(
            assignments=scoped,
            scope=scope,
            db=db,
        )
        if not options:
            continue
        if effective is None:
            effective = options
            continue
        narrowed: dict[str, _EffectivePublicModel] = {}
        for name, child_model in options.items():
            parent_model = effective.get(name)
            if parent_model is None:
                continue
            parent_keys = {candidate.key for candidate in parent_model.candidates}
            candidates = [
                candidate for candidate in child_model.candidates if candidate.key in parent_keys
            ]
            if candidates:
                narrowed[name] = child_model.with_candidates(candidates)
        effective = narrowed
    return effective or {}


async def _effective_access_public_model_options(
    *,
    assignments: list[PolicyAssignment],
    scope: Scope,
    db: AsyncSession,
) -> dict[str, "_EffectivePublicModel"]:
    effective: dict[str, _EffectivePublicModel] | None = None
    for scope_type in ("org", "team", "project", "virtual_key"):
        options = await _public_model_options_from_assignments(
            assignments=[
                assignment for assignment in assignments if assignment.scope_type == scope_type
            ],
            scope=scope,
            db=db,
        )
        if not options:
            continue
        if effective is None:
            effective = options
            continue
        narrowed: dict[str, _EffectivePublicModel] = {}
        for name, child_model in options.items():
            parent_model = effective.get(name)
            if parent_model is None:
                continue
            parent_keys = {candidate.key for candidate in parent_model.candidates}
            candidates = [
                candidate for candidate in child_model.candidates if candidate.key in parent_keys
            ]
            if candidates:
                narrowed[name] = child_model.with_candidates(candidates)
        effective = narrowed
    return effective or {}


async def _public_model_options_from_assignments(
    *,
    assignments: list[PolicyAssignment],
    scope: Scope,
    db: AsyncSession,
) -> dict[str, "_EffectivePublicModel"]:
    options: dict[str, _EffectivePublicModel] = {}
    for assignment in assignments:
        policy = await repository.get_access_policy_by_shared_policy(
            shared_policy_id=assignment.policy_id,
            org_id=scope.org_id,
            db=db,
        )
        if policy is None or not policy.is_active:
            continue
        public_models = await repository.list_access_policy_public_models(
            org_id=scope.org_id,
            access_policy_id=policy.id,
            db=db,
        )
        for public_model in public_models:
            if not public_model.is_active:
                continue
            candidates = [
                _EffectivePublicModelCandidate(
                    provider_id=candidate.provider_id,
                    credential_pool_id=candidate.credential_pool_id,
                    model_id=candidate.model_offering_id,
                )
                for candidate in await repository.list_access_policy_route_candidates(
                    org_id=scope.org_id,
                    public_model_id=public_model.id,
                    db=db,
                )
                if candidate.is_active
            ]
            if candidates:
                options[public_model.public_model_name] = _EffectivePublicModel(
                    routing_mode=public_model.routing_mode,
                    fallback_on=list(public_model.fallback_on),
                    max_route_attempts=public_model.max_route_attempts,
                    candidates=candidates,
                )
    return options


async def _validate_scoped_access_policy_public_models(
    *,
    public_models: list[AccessPolicyPublicModelInput],
    parent_public_models: dict[str, "_EffectivePublicModel"],
    scope: Scope,
    db: AsyncSession,
) -> None:
    validate_scoped_access_policy_public_model_payload(
        public_models=public_models,
        parent_public_models=parent_public_models,
    )


_EffectivePublicModelCandidate = EffectiveAccessPolicyCandidate
_EffectivePublicModel = EffectiveAccessPolicyPublicModel


async def _validate_limit_rule_filters(
    *, payload: LimitPolicyRuleInput, scope: Scope, db: AsyncSession
) -> None:
    validate_limit_rule_payload(payload)
    try:
        if payload.provider_id is not None:
            await providers_facade.get_provider(provider_id=payload.provider_id, scope=scope, db=db)
        if payload.credential_pool_id is not None:
            await providers_facade.get_credential_pool(
                pool_id=payload.credential_pool_id, scope=scope, db=db
            )
        if payload.model_offering_id is not None:
            await providers_facade.get_model_offering(
                model_offering_id=payload.model_offering_id, scope=scope, db=db
            )
        if payload.access_policy_id is not None:
            await _get_access_policy_or_raise(
                policy_id=payload.access_policy_id, scope=scope, db=db
            )
    except (ProviderNotFoundError, PolicyNotFoundError) as exc:
        raise PolicyValidationError from exc


async def _validate_assignment_policy(
    *, payload: CreatePolicyAssignmentRequest, scope: Scope, db: AsyncSession
) -> AccessPolicy | LimitPolicy:
    shared_policy = await policy_kernel_repository.get_policy(
        org_id=scope.org_id,
        policy_id=payload.policy_id,
        db=db,
    )
    if shared_policy is None or shared_policy.kind != payload.policy_type:
        raise PolicyValidationError
    if payload.policy_type == "access":
        policy = await repository.get_access_policy_by_shared_policy(
            shared_policy_id=payload.policy_id,
            org_id=scope.org_id,
            db=db,
        )
    else:
        policy = await repository.get_limit_policy_by_shared_policy(
            shared_policy_id=payload.policy_id,
            org_id=scope.org_id,
            db=db,
        )
    if policy is None:
        raise PolicyValidationError
    _validate_policy_assignment_scope(policy=policy, payload=payload)
    return policy


def _assignment_shared_policy_id(policy: AccessPolicy | LimitPolicy) -> UUID:
    return policy.policy_id


def _assignment_scope_target_key(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> str:
    try:
        return assignment_scope_target_key(
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )
    except ValueError as exc:
        raise PolicyValidationError from exc


async def _validate_no_same_scope_public_model_conflicts(
    *,
    payload: CreatePolicyAssignmentRequest,
    access_policy_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> None:
    new_models = await repository.list_access_policy_public_models(
        org_id=scope.org_id,
        access_policy_id=access_policy_id,
        db=db,
    )
    new_names = {model.public_model_name for model in new_models if model.is_active}
    if not new_names:
        return
    assignments = await policy_kernel_repository.list_policy_assignments(
        org_id=scope.org_id, db=db
    )
    for assignment in assignments:
        if (
            not assignment.is_active
            or assignment.policy_type != "access"
            or assignment.policy_id == payload.policy_id
            or assignment.scope_type != payload.scope_type
            or assignment.team_id != payload.team_id
            or assignment.project_id != payload.project_id
            or assignment.virtual_key_id != payload.virtual_key_id
        ):
            continue
        existing_policy = await repository.get_access_policy_by_shared_policy(
            org_id=scope.org_id,
            shared_policy_id=assignment.policy_id,
            db=db,
        )
        if existing_policy is None or not existing_policy.is_active:
            continue
        existing_models = await repository.list_access_policy_public_models(
            org_id=scope.org_id,
            access_policy_id=existing_policy.id,
            db=db,
        )
        existing_names = {model.public_model_name for model in existing_models if model.is_active}
        if new_names & existing_names:
            raise PolicyAssignmentConflictError


async def _validate_update_public_model_assignment_conflicts(
    *,
    policy_id: UUID,
    public_models: list[AccessPolicyPublicModelInput],
    scope: Scope,
    db: AsyncSession,
) -> None:
    proposed_names = {
        public_model.public_model_name.strip()
        for public_model in public_models
        if public_model.is_active
    }
    if not proposed_names:
        return
    policy = await _get_access_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
    assignments = await policy_kernel_repository.list_policy_assignments_for_policy(
        org_id=scope.org_id,
        policy_id=policy.policy_id,
        active_only=True,
        db=db,
    )
    all_assignments = await policy_kernel_repository.list_policy_assignments(
        org_id=scope.org_id, db=db
    )
    for assignment in assignments:
        for existing in all_assignments:
            if (
                not existing.is_active
                or existing.policy_type != "access"
                or existing.policy_id == policy.policy_id
                or existing.scope_type != assignment.scope_type
                or existing.team_id != assignment.team_id
                or existing.project_id != assignment.project_id
                or existing.virtual_key_id != assignment.virtual_key_id
            ):
                continue
            existing_policy = await repository.get_access_policy_by_shared_policy(
                org_id=scope.org_id,
                shared_policy_id=existing.policy_id,
                db=db,
            )
            if existing_policy is None or not existing_policy.is_active:
                continue
            existing_models = await repository.list_access_policy_public_models(
                org_id=scope.org_id,
                access_policy_id=existing_policy.id,
                db=db,
            )
            existing_names = {
                public_model.public_model_name
                for public_model in existing_models
                if public_model.is_active
            }
            if proposed_names & existing_names:
                raise PolicyAssignmentConflictError


def _validate_policy_assignment_scope(
    *, policy: AccessPolicy | LimitPolicy, payload: CreatePolicyAssignmentRequest
) -> None:
    if policy.owning_scope_type is None:
        return
    expected = _policy_owner_tuple(policy)
    actual = (
        payload.scope_type,
        payload.team_id,
        payload.project_id,
        payload.virtual_key_id,
    )
    if actual != expected:
        raise PolicyValidationError


def _policy_owner_tuple(
    policy: AccessPolicy | LimitPolicy,
) -> tuple[str | None, UUID | None, UUID | None, UUID | None]:
    return (
        policy.owning_scope_type,
        policy.owning_team_id,
        policy.owning_project_id,
        policy.owning_virtual_key_id,
    )


async def _can_view_policy(
    *,
    policy: AccessPolicy | LimitPolicy,
    actor: AuthenticatedUser | None,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    if actor is None or _is_org_policy_viewer(actor):
        return True
    if policy.owning_scope_type is None:
        return _has_scoped_admin_membership(actor)
    return await _is_admin_for_scope(
        actor=actor,
        scope_type=policy.owning_scope_type,
        team_id=policy.owning_team_id,
        project_id=policy.owning_project_id,
        virtual_key_id=policy.owning_virtual_key_id,
        scope=scope,
        db=db,
    )


async def _can_manage_policy_definition(
    *,
    policy: AccessPolicy | LimitPolicy,
    actor: AuthenticatedUser | None,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    if actor is None or _is_org_policy_admin(actor):
        return True
    if policy.owning_scope_type is None:
        return False
    return await _is_admin_for_scope(
        actor=actor,
        scope_type=policy.owning_scope_type,
        team_id=policy.owning_team_id,
        project_id=policy.owning_project_id,
        virtual_key_id=policy.owning_virtual_key_id,
        scope=scope,
        db=db,
    )


def _is_org_policy_admin(actor: AuthenticatedUser) -> bool:
    return "*" in actor.permissions or actor.role in {"super_admin", "org_owner", "org_admin"}


def _is_org_policy_viewer(actor: AuthenticatedUser) -> bool:
    return "*" in actor.permissions or actor.role in {
        "super_admin",
        "org_owner",
        "org_admin",
        "org_viewer",
    }


def _has_scoped_admin_membership(actor: AuthenticatedUser) -> bool:
    return any(membership.role == "team_admin" for membership in actor.team_memberships) or any(
        membership.role == "project_admin" for membership in actor.project_memberships
    )


async def _is_admin_for_scope(
    *,
    actor: AuthenticatedUser,
    scope_type: str | None,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    team_admin_ids = {
        membership.team_id
        for membership in actor.team_memberships
        if membership.role == "team_admin"
    }
    project_admin_ids = {
        membership.project_id
        for membership in actor.project_memberships
        if membership.role == "project_admin"
    }
    if scope_type == "team":
        return team_id in team_admin_ids
    if scope_type == "project":
        if project_id is None:
            return False
        project = await repository.get_project(org_id=scope.org_id, project_id=project_id, db=db)
        return project is not None and (
            project.id in project_admin_ids or project.team_id in team_admin_ids
        )
    if scope_type == "virtual_key":
        if virtual_key_id is None:
            return False
        virtual_key = await repository.get_virtual_key(
            org_id=scope.org_id, virtual_key_id=virtual_key_id, db=db
        )
        if virtual_key is None:
            return False
        project = await repository.get_project(
            org_id=scope.org_id, project_id=virtual_key.project_id, db=db
        )
        return project is not None and (
            project.id in project_admin_ids or project.team_id in team_admin_ids
        )
    return False


async def _can_view_assignment(
    *,
    assignment: PolicyAssignment,
    actor: AuthenticatedUser | None,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    if actor is None or _is_org_policy_viewer(actor):
        return True
    return await _is_admin_for_scope(
        actor=actor,
        scope_type=assignment.scope_type,
        team_id=assignment.team_id,
        project_id=assignment.project_id,
        virtual_key_id=assignment.virtual_key_id,
        scope=scope,
        db=db,
    )


async def _policy_impact_from_assignments(
    *,
    assignments: list[PolicyAssignment],
    scope: Scope,
    db: AsyncSession,
    exclude_access_policy_id: UUID | None = None,
) -> PolicyImpactResponse:
    teams: dict[UUID, PolicyImpactTarget] = {}
    projects: dict[UUID, PolicyImpactTarget] = {}
    virtual_keys: dict[UUID, PolicyImpactVirtualKey] = {}

    affected_project_ids = await _affected_project_ids(
        assignments=assignments,
        scope=scope,
        db=db,
        teams=teams,
        projects=projects,
    )
    for key, project in await repository.list_virtual_keys_for_project_ids(
        org_id=scope.org_id,
        project_ids=list(affected_project_ids),
        db=db,
    ):
        virtual_keys[key.id] = PolicyImpactVirtualKey(
            id=key.id,
            name=key.name,
            project_id=project.id,
            project_name=project.name,
        )
    direct_key_ids = [
        assignment.virtual_key_id for assignment in assignments if assignment.virtual_key_id
    ]
    for key, project in await repository.list_virtual_keys_by_ids(
        org_id=scope.org_id,
        virtual_key_ids=direct_key_ids,
        db=db,
    ):
        virtual_keys[key.id] = PolicyImpactVirtualKey(
            id=key.id,
            name=key.name,
            project_id=project.id,
            project_name=project.name,
        )
        projects.setdefault(project.id, PolicyImpactTarget(id=project.id, name=project.name))

    unusable: dict[UUID, PolicyImpactVirtualKey] = {}
    if exclude_access_policy_id is not None:
        for key_id, key in virtual_keys.items():
            has_access = await _target_has_routable_access_after_exclusion(
                org_id=scope.org_id,
                virtual_key_id=key_id,
                project_id=key.project_id,
                exclude_access_policy_id=exclude_access_policy_id,
                db=db,
            )
            if not has_access:
                unusable[key_id] = key

    return PolicyImpactResponse(
        affected_teams=sorted(teams.values(), key=lambda item: item.name),
        affected_projects=sorted(projects.values(), key=lambda item: item.name),
        affected_virtual_keys=sorted(virtual_keys.values(), key=lambda item: item.name),
        affected_team_count=len(teams),
        affected_project_count=len(projects),
        affected_virtual_key_count=len(virtual_keys),
        virtual_keys_would_become_unusable=sorted(unusable.values(), key=lambda item: item.name),
        virtual_keys_would_become_unusable_count=len(unusable),
    )


async def _affected_project_ids(
    *,
    assignments: list[PolicyAssignment],
    scope: Scope,
    db: AsyncSession,
    teams: dict[UUID, PolicyImpactTarget],
    projects: dict[UUID, PolicyImpactTarget],
) -> set[UUID]:
    project_ids: set[UUID] = set()
    org_assigned = any(assignment.scope_type == "org" for assignment in assignments)
    if org_assigned:
        for project in await repository.list_all_projects(org_id=scope.org_id, db=db):
            project_ids.add(project.id)
            projects[project.id] = PolicyImpactTarget(id=project.id, name=project.name)

    team_ids = [assignment.team_id for assignment in assignments if assignment.team_id]
    for team_id in team_ids:
        team = await repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
        if team is not None:
            teams[team.id] = PolicyImpactTarget(id=team.id, name=team.name)
    for project in await repository.list_projects_for_team_ids(
        org_id=scope.org_id,
        team_ids=team_ids,
        db=db,
    ):
        project_ids.add(project.id)
        projects[project.id] = PolicyImpactTarget(id=project.id, name=project.name)

    for assignment in assignments:
        if assignment.project_id is None:
            continue
        project = await repository.get_project(
            org_id=scope.org_id,
            project_id=assignment.project_id,
            db=db,
        )
        if project is not None:
            project_ids.add(project.id)
            projects[project.id] = PolicyImpactTarget(id=project.id, name=project.name)
    return project_ids


async def _target_has_routable_access_after_exclusion(
    *,
    org_id: UUID,
    virtual_key_id: UUID,
    project_id: UUID,
    exclude_access_policy_id: UUID | None,
    db: AsyncSession,
) -> bool:
    project = await repository.get_project(org_id=org_id, project_id=project_id, db=db)
    if project is None:
        return False
    assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key_id,
        policy_type="access",
        db=db,
    )
    exclude_shared_policy_id: UUID | None = None
    if exclude_access_policy_id is not None:
        excluded_policy = await repository.get_access_policy(
            policy_id=exclude_access_policy_id,
            org_id=org_id,
            db=db,
        )
        exclude_shared_policy_id = excluded_policy.policy_id if excluded_policy else None
    effective = await _effective_access_public_model_options(
        assignments=[
            assignment
            for assignment in assignments
            if assignment.policy_id != exclude_shared_policy_id
        ],
        scope=Scope(org_id=org_id),
        db=db,
    )
    for public_model in effective.values():
        for candidate in public_model.candidates:
            if await _is_routable_provider_pool_model(
                provider_id=candidate.provider_id,
                pool_id=candidate.credential_pool_id,
                model_id=candidate.model_id,
                scope=Scope(org_id=org_id),
                db=db,
            ):
                return True
    return False


async def _validate_assignment_target(
    *,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    try:
        validated = await _workspace_access.validate_assignment_scope(
            organization_id=scope.org_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
    except ScopeNotFoundError as exc:
        if exc.reason == "not_found":
            raise PolicyNotFoundError from exc
        raise PolicyValidationError from exc
    return validated.team_id, validated.project_id, validated.virtual_key_id


async def _is_routable_provider_pool_model(
    *,
    provider_id: UUID,
    pool_id: UUID,
    model_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> bool:
    try:
        provider = await providers_facade.get_provider(provider_id=provider_id, scope=scope, db=db)
        pool = await providers_facade.get_credential_pool(pool_id=pool_id, scope=scope, db=db)
        model = await providers_facade.get_model_offering(
            model_offering_id=model_id, scope=scope, db=db
        )
    except ProviderNotFoundError:
        return False
    return (
        provider.is_active
        and pool.is_active
        and model.is_active
        and pool.provider_id == provider.id
        and model.provider_id == provider.id
        and await _pool_has_active_credential(
            provider_id=provider.id, pool_id=pool.id, scope=scope, db=db
        )
    )


async def _pool_has_active_credential(
    *, provider_id: UUID, pool_id: UUID, scope: Scope, db: AsyncSession
) -> bool:
    credentials = await providers_facade.list_credential_pool_credentials(
        provider_id=provider_id,
        pool_id=pool_id,
        scope=scope,
        db=db,
    )
    return any(item.is_active and item.credential.is_active for item in credentials)


async def _record_policy_activity(
    *,
    actor: AuthenticatedUser | None,
    scope: Scope,
    action: str,
    message: str,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    if actor is None:
        return
    audit_entity_type, audit_entity_id = _policy_audit_entity(metadata)
    await activity_facade.record_admin_event(
        actor=actor,
        category="policy",
        action=action,
        message=message,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        audit_entity_type=audit_entity_type,
        audit_entity_id=audit_entity_id,
        metadata=metadata,
        db=db,
    )


def _policy_audit_entity(metadata: dict) -> tuple[str, UUID | None]:
    for entity_type, key in (
        ("policy_assignment", "assignment_id"),
        ("access_policy_route", "access_policy_route_id"),
        ("limit_policy_rule", "limit_policy_rule_id"),
        ("access_policy", "access_policy_id"),
        ("limit_policy", "limit_policy_id"),
    ):
        value = metadata.get(key)
        if value:
            return entity_type, UUID(str(value))
    return "organization", None


async def _assignment_activity_scope_ids(
    *, scope: Scope, assignment: PolicyAssignment, db: AsyncSession
) -> tuple[UUID | None, UUID | None]:
    if assignment.team_id is not None:
        return assignment.team_id, None
    if assignment.project_id is not None:
        project = await repository.get_project(
            org_id=scope.org_id,
            project_id=assignment.project_id,
            db=db,
        )
        return (project.team_id if project is not None else None), assignment.project_id
    if assignment.virtual_key_id is not None:
        virtual_key = await repository.get_virtual_key(
            org_id=scope.org_id,
            virtual_key_id=assignment.virtual_key_id,
            db=db,
        )
        if virtual_key is None:
            return None, None
        project = await repository.get_project(
            org_id=scope.org_id,
            project_id=virtual_key.project_id,
            db=db,
        )
        return (project.team_id if project is not None else None), virtual_key.project_id
    return None, None


def _assignment_metadata(assignment: PolicyAssignment) -> dict:
    return {
        "assignment_id": str(assignment.id),
        "policy_id": str(assignment.policy_id),
        "policy_type": assignment.policy_type,
        "scope_type": assignment.scope_type,
        "team_id": str(assignment.team_id) if assignment.team_id else None,
        "project_id": str(assignment.project_id) if assignment.project_id else None,
        "virtual_key_id": str(assignment.virtual_key_id) if assignment.virtual_key_id else None,
    }
