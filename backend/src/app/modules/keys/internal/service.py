from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import generate_virtual_key, hash_token
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    PolicyNotConfiguredError,
    ProjectNotFoundError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.keys.schemas import (
    AccessibleModel,
    CreatedVirtualKeyResponse,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    ProjectResponse,
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedLimitPolicy,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
)
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.internal.models import (
    AccessPolicyRoute,
    LimitPolicy,
    LimitPolicyRule,
    PolicyAssignment,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.settings import facade as settings_facade
from app.modules.teams import facade as teams_facade

logger = structlog.get_logger(__name__)


type ResolvedKeyProject = tuple[VirtualKey, Project]
type ResolvedPolicyRoute = tuple[
    AccessPolicyRoute,
    UUID,
    UUID,
    str,
    int | None,
    int | None,
]


async def create_project(
    *,
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    async with transaction(db):
        await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
        project = await repository.create_project(
            org_id=scope.org_id,
            team_id=team_id,
            created_by=actor.id,
            name=payload.name,
            description=payload.description,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.created",
            message=f"Created project {project.name}.",
            team_id=team_id,
            project_id=project.id,
            db=db,
        )
    logger.info("project_created", project_id=str(project.id), org_id=str(scope.org_id))
    return _to_project_response(project)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    projects = await repository.list_projects(org_id=scope.org_id, db=db)
    return [_to_project_response(project) for project in projects]


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return _to_project_response(project)


async def list_team_projects(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectResponse]:
    await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
    projects = await repository.list_team_projects(org_id=scope.org_id, team_id=team_id, db=db)
    return [_to_project_response(project) for project in projects]


async def update_project(
    *,
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        if payload.name is not None:
            project.name = payload.name
        if "description" in payload.model_fields_set:
            project.description = payload.description
        if payload.is_active is not None:
            project.is_active = payload.is_active
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.updated",
            message=f"Updated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            db=db,
        )
    logger.info(
        "project_updated",
        project_id=str(project.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _to_project_response(project)


async def deactivate_project(
    *,
    project_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        project.is_active = False
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.deactivated",
            message=f"Deactivated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            db=db,
        )
    logger.info(
        "project_deactivated",
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


async def create_virtual_key(
    *,
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        access_routes = await _effective_access_routes(
            org_id=scope.org_id,
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=None,
            db=db,
        )
        limit_policies = await _effective_limit_policies(
            org_id=scope.org_id,
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=None,
            db=db,
        )
        if not access_routes or not limit_policies:
            raise PolicyNotConfiguredError
        raw_key = generate_virtual_key(prefix=org_settings.virtual_key_prefix)
        expires_at = payload.expires_at
        if expires_at is None and org_settings.default_virtual_key_expiration_days is not None:
            expires_at = datetime.now(UTC) + timedelta(
                days=org_settings.default_virtual_key_expiration_days
            )
        virtual_key = await repository.create_virtual_key(
            org_id=scope.org_id,
            project_id=project.id,
            name=payload.name,
            key_hash=hash_token(raw_key),
            key_prefix=_key_prefix(raw_key),
            allowed_models=payload.allowed_models,
            expires_at=expires_at,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.created",
            message=f"Created virtual key {virtual_key.name}.",
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_created",
        virtual_key_id=str(virtual_key.id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    response = await _to_virtual_key_response(
        virtual_key,
        project=project,
        scope=scope,
        db=db,
    )
    return CreatedVirtualKeyResponse(
        **response.model_dump(),
        key=raw_key if org_settings.allow_secret_copy else None,
    )


async def list_virtual_keys(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[VirtualKeyResponse]:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_keys = await repository.list_virtual_keys(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    return [
        await _to_virtual_key_response(
            virtual_key,
            project=project,
            scope=scope,
            db=db,
        )
        for virtual_key in virtual_keys
    ]


async def get_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_key = await _get_virtual_key_or_raise(
        project_id=project_id,
        key_id=key_id,
        scope=scope,
        db=db,
    )
    return await _to_virtual_key_response(
        virtual_key,
        project=project,
        scope=scope,
        db=db,
    )


async def update_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: UpdateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        if payload.name is not None:
            virtual_key.name = payload.name
        if "expires_at" in payload.model_fields_set:
            virtual_key.expires_at = payload.expires_at
        if "allowed_models" in payload.model_fields_set:
            virtual_key.allowed_models = payload.allowed_models
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.updated",
            message=f"Updated virtual key {virtual_key.name}.",
            project_id=project_id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_updated",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return await _to_virtual_key_response(
        virtual_key,
        project=project,
        scope=scope,
        db=db,
    )


async def revoke_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        virtual_key.revoked_at = datetime.now(UTC)
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.revoked",
            message=f"Revoked virtual key {virtual_key.name}.",
            project_id=project_id,
            virtual_key_id=virtual_key.id,
            db=db,
        )
    logger.info(
        "virtual_key_revoked",
        virtual_key_id=str(key_id),
        project_id=str(project_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    virtual_key, project = await _resolve_key_project(
        raw_key=payload.raw_key,
        db=db,
    )
    matched = await _match_policy_route(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        requested_model=payload.requested_model,
        db=db,
    )
    if matched is None:
        raise AccessDeniedError
    route, model_offering_id, provider_id, pool_id, provider_model, input_price, output_price = (
        matched
    )
    if virtual_key.allowed_models is not None and provider_model not in virtual_key.allowed_models:
        raise AccessDeniedError
    limit_rules = await _matching_limit_policies(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        route=route,
        model_offering_id=model_offering_id,
        db=db,
    )
    if not limit_rules:
        raise AccessDeniedError

    return ResolvedAccess(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=virtual_key.project_id,
        access_policy_id=route.access_policy_id,
        access_policy_route_id=route.id,
        model_offering_id=model_offering_id,
        limit_policy_ids=list({rule.limit_policy_id for rule in limit_rules}),
        limit_policies=[_to_resolved_limit_policy(rule) for rule in limit_rules],
        virtual_key_id=virtual_key.id,
        provider_id=provider_id,
        pool_id=pool_id,
        provider_key_id=None,
        requested_model=payload.requested_model,
        provider_model=provider_model,
        input_price_per_million_tokens=input_price,
        output_price_per_million_tokens=output_price,
    )


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    virtual_key, project = await _resolve_key_project(
        raw_key=raw_key,
        db=db,
    )
    models: list[AccessibleModel] = []
    seen: set[str] = set()
    for route, model_offering_id in await _effective_access_routes(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    ):
        try:
            pool = await providers_facade.get_credential_pool(
                pool_id=route.credential_pool_id,
                scope=Scope(org_id=virtual_key.org_id),
                db=db,
            )
            model = await providers_facade.get_model_offering(
                model_offering_id=model_offering_id,
                scope=Scope(org_id=virtual_key.org_id),
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if not pool.is_active or not model.is_active or pool.provider_id != model.provider_id:
            continue
        if (
            virtual_key.allowed_models is not None
            and model.provider_model_name not in virtual_key.allowed_models
        ):
            continue
        limit_policies = await _matching_limit_policies(
            org_id=virtual_key.org_id,
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            route=route,
            model_offering_id=model_offering_id,
            db=db,
        )
        if not limit_policies:
            continue
        if model.provider_model_name in seen:
            continue
        seen.add(model.provider_model_name)
        models.append(
            AccessibleModel(
                id=model.provider_model_name,
                owned_by=model.provider_id.hex,
                provider_id=model.provider_id,
                access_policy_id=route.access_policy_id,
                access_policy_route_id=route.id,
                pool_id=pool.id,
                alias=model.alias,
            )
        )
    return models


async def _resolve_key_project(*, raw_key: str, db: AsyncSession) -> ResolvedKeyProject:
    virtual_key = await repository.get_virtual_key_by_hash(key_hash=hash_token(raw_key), db=db)
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    project = await repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError
    return virtual_key, project


async def _match_policy_route(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    requested_model: str,
    db: AsyncSession,
) -> ResolvedPolicyRoute | None:
    candidates = await _effective_access_routes(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    candidates.sort(key=lambda item: (item[0].priority, -item[0].weight, item[0].created_at))
    for route, model_offering_id in candidates:
        try:
            pool = await providers_facade.get_credential_pool(
                pool_id=route.credential_pool_id,
                scope=Scope(org_id=org_id),
                db=db,
            )
            model = await providers_facade.get_model_offering(
                model_offering_id=model_offering_id,
                scope=Scope(org_id=org_id),
                db=db,
            )
        except ProviderNotFoundError:
            continue
        if not pool.is_active or not model.is_active:
            continue
        if pool.provider_id != model.provider_id or model.provider_id != route.provider_id:
            continue
        if requested_model not in {model.provider_model_name, model.alias}:
            continue
        return (
            route,
            model.id,
            model.provider_id,
            pool.id,
            model.provider_model_name,
            model.effective_input_price_per_million_tokens,
            model.effective_output_price_per_million_tokens,
        )
    return None


async def _effective_access_routes(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[tuple[AccessPolicyRoute, UUID]]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="access",
        db=db,
    )
    effective: list[tuple[AccessPolicyRoute, UUID]] | None = None
    for scope_type in ("org", "team", "project", "virtual_key"):
        scoped = [assignment for assignment in assignments if assignment.scope_type == scope_type]
        candidates = await _access_route_candidates(org_id=org_id, assignments=scoped, db=db)
        if not candidates:
            continue
        if effective is None:
            effective = candidates
            continue
        effective = [
            candidate
            for candidate in candidates
            if any(_route_candidate_matches(candidate, ancestor) for ancestor in effective)
        ]
    return effective or []


async def _access_route_candidates(
    *,
    org_id: UUID,
    assignments: list[PolicyAssignment],
    db: AsyncSession,
) -> list[tuple[AccessPolicyRoute, UUID]]:
    candidates: list[tuple[AccessPolicyRoute, UUID]] = []
    for assignment in assignments:
        if assignment.access_policy_id is None:
            continue
        policy = await policies_repository.get_access_policy(
            policy_id=assignment.access_policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is None or not policy.is_active:
            continue
        routes = await policies_repository.list_access_policy_routes(
            org_id=org_id,
            access_policy_id=policy.id,
            db=db,
        )
        for route in routes:
            if not route.is_active:
                continue
            candidates.extend((route, UUID(str(model_id))) for model_id in route.model_offering_ids)
    return candidates


def _route_candidate_matches(
    child: tuple[AccessPolicyRoute, UUID],
    ancestor: tuple[AccessPolicyRoute, UUID],
) -> bool:
    child_route, child_model_id = child
    ancestor_route, ancestor_model_id = ancestor
    return (
        child_route.provider_id == ancestor_route.provider_id
        and child_route.credential_pool_id == ancestor_route.credential_pool_id
        and child_model_id == ancestor_model_id
    )


async def _effective_limit_policies(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[LimitPolicy]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    policies: list[LimitPolicy] = []
    for assignment in assignments:
        if assignment.limit_policy_id is None:
            continue
        policy = await policies_repository.get_limit_policy(
            policy_id=assignment.limit_policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is not None and policy.is_active:
            policies.append(policy)
    return policies


async def _matching_limit_policies(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    route: AccessPolicyRoute,
    model_offering_id: UUID,
    db: AsyncSession,
) -> list[LimitPolicyRule]:
    policies = await _effective_limit_policies(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    rules: list[LimitPolicyRule] = []
    for policy in policies:
        policy_rules = await policies_repository.list_limit_policy_rules(
            org_id=org_id,
            limit_policy_id=policy.id,
            db=db,
        )
        rules.extend(
            rule
            for rule in policy_rules
            if rule.is_active
            and _limit_rule_matches_route(
                rule=rule,
                route=route,
                model_offering_id=model_offering_id,
            )
        )
    return rules


def _limit_rule_matches_route(
    *,
    rule: LimitPolicyRule,
    route: AccessPolicyRoute,
    model_offering_id: UUID,
) -> bool:
    return (
        (rule.provider_id is None or rule.provider_id == route.provider_id)
        and (rule.credential_pool_id is None or rule.credential_pool_id == route.credential_pool_id)
        and (rule.model_offering_id is None or rule.model_offering_id == model_offering_id)
        and (rule.access_policy_id is None or rule.access_policy_id == route.access_policy_id)
    )


async def _get_project_or_raise(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        raise ProjectNotFoundError
    return project


async def _get_virtual_key_or_raise(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKey:
    virtual_key = await repository.get_virtual_key(
        org_id=scope.org_id,
        project_id=project_id,
        key_id=key_id,
        db=db,
    )
    if virtual_key is None:
        raise VirtualKeyNotFoundError
    return virtual_key


def _to_project_response(project: Project) -> ProjectResponse:
    return ProjectResponse.model_validate(project)


def _to_resolved_limit_policy(policy: LimitPolicyRule) -> ResolvedLimitPolicy:
    return ResolvedLimitPolicy(
        limit_policy_id=policy.limit_policy_id,
        limit_policy_rule_id=policy.id,
        name=policy.name,
        budget_cents=policy.budget_cents,
        max_requests=policy.max_requests,
        max_input_tokens=policy.max_input_tokens,
        max_output_tokens=policy.max_output_tokens,
        max_tokens_per_request=policy.max_tokens_per_request,
        window=policy.window,
    )


async def _to_virtual_key_response(
    virtual_key: VirtualKey,
    *,
    project: Project,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    return VirtualKeyResponse(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        allowed_models=virtual_key.allowed_models,
        expires_at=virtual_key.expires_at,
        revoked_at=virtual_key.revoked_at,
        created_at=virtual_key.created_at,
        updated_at=virtual_key.updated_at,
    )


def _key_prefix(raw_key: str) -> str:
    return raw_key[:16]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
