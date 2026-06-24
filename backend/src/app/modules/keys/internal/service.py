import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import generate_virtual_key, hash_token
from app.modules.activity import facade as activity_facade
from app.modules.auth.internal.models import Team, User
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
    OrganizationInactiveError,
    PolicyNotConfiguredError,
    ProjectAccessUnavailableError,
    ProjectInactiveError,
    ProjectNotFoundError,
    ProjectSlugAlreadyExistsError,
    SecretDeliveryDisabledError,
    VirtualKeyAlreadyRevokedError,
    VirtualKeyNotFoundError,
    VirtualKeyOverlapActiveError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.keys.runtime_routes import (
    ResolvedAccessPlanExplanation,
    RouteCandidateExplanation,
)
from app.modules.keys.schemas import (
    AccessibleModel,
    AccessibleModelCandidate,
    CreatedVirtualKeyResponse,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    EffectiveAccessSummary,
    EffectiveLimitReference,
    EffectivePolicyReference,
    EffectiveRouteSummary,
    OwnershipChainState,
    ProjectArchiveImpactResponse,
    ProjectResponse,
    ResolveAccessPlanForSubjectRequest,
    ResolveAccessPlanForVirtualKeyRequest,
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedAccessPlan,
    ResolvedKeySubject,
    ResolvedLimitPolicy,
    ResolvedRouteAttempt,
    ResolveKeySubjectRequest,
    RotateVirtualKeyRequest,
    TeamArchiveImpactResponse,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyInventoryItem,
    VirtualKeyInventoryPage,
    VirtualKeyResponse,
    VirtualKeyRevokeImpactResponse,
)
from app.modules.policies.internal import repository as policies_repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import PolicyAssignment
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.settings import facade as settings_facade
from app.modules.teams import facade as teams_facade
from app.modules.teams.errors import TeamInactiveError, TeamNotFoundError

logger = structlog.get_logger(__name__)
EXPIRING_SOON_DAYS = 7
IMPACT_USAGE_WINDOW_DAYS = 30


type ResolvedKeyProject = tuple[VirtualKey, Project]
type EffectiveAccessRouteCandidate = tuple[
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    PolicyAssignment,
]
type ResolvedPolicyRoute = tuple[
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    PolicyAssignment,
    ModelOffering,
    CredentialPool,
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
    slug = _slugify(payload.slug or payload.name)
    async with transaction(db):
        await _ensure_organization_active(org_id=scope.org_id, db=db)
        await teams_facade.ensure_team_active(team_id=team_id, scope=scope, db=db)
        await _ensure_project_slug_available(
            org_id=scope.org_id,
            team_id=team_id,
            slug=slug,
            db=db,
        )
        try:
            project = await repository.create_project(
                org_id=scope.org_id,
                team_id=team_id,
                created_by=actor.id,
                name=payload.name,
                slug=slug,
                description=payload.description,
                db=db,
            )
        except IntegrityError as exc:
            raise ProjectSlugAlreadyExistsError from exc
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="project.created",
            message=f"Created project {project.name}.",
            team_id=team_id,
            project_id=project.id,
            metadata={"project_id": str(project.id), "team_id": str(team_id)},
            db=db,
        )
    logger.info("project_created", project_id=str(project.id), org_id=str(scope.org_id))
    return await _to_project_response(project, db=db)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    projects = await repository.list_projects(org_id=scope.org_id, db=db)
    return [await _to_project_response(project, db=db) for project in projects]


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return await _to_project_response(project, db=db)


async def list_team_projects(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectResponse]:
    await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
    projects = await repository.list_team_projects(org_id=scope.org_id, team_id=team_id, db=db)
    return [await _to_project_response(project, db=db) for project in projects]


async def get_team_archive_impact(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> TeamArchiveImpactResponse:
    await teams_facade.get_team(team_id=team_id, scope=scope, db=db)
    since = datetime.now(UTC) - timedelta(days=IMPACT_USAGE_WINDOW_DAYS)
    request_count, cost_cents = await repository.summarize_recent_usage(
        org_id=scope.org_id,
        since=since,
        team_id=team_id,
        project_id=None,
        virtual_key_id=None,
        db=db,
    )
    team_admin_count, team_member_count = await repository.count_team_members_by_role(
        org_id=scope.org_id,
        team_id=team_id,
        db=db,
    )
    return TeamArchiveImpactResponse(
        active_project_count=await repository.count_active_team_projects(
            org_id=scope.org_id,
            team_id=team_id,
            db=db,
        ),
        active_virtual_key_count=await repository.count_active_team_virtual_keys(
            org_id=scope.org_id,
            team_id=team_id,
            db=db,
        ),
        team_admin_count=team_admin_count,
        team_member_count=team_member_count,
        recent_usage_window_days=IMPACT_USAGE_WINDOW_DAYS,
        recent_request_count=request_count,
        recent_cost_cents=cost_cents,
    )


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
        changed_fields: dict[str, dict[str, object]] = {}
        if payload.slug is not None:
            slug = _slugify(payload.slug)
            if slug != project.slug:
                await _ensure_project_slug_available(
                    org_id=scope.org_id,
                    team_id=project.team_id,
                    slug=slug,
                    db=db,
                )
                changed_fields["slug"] = {"from": project.slug, "to": slug}
                project.slug = slug
        if payload.name is not None:
            if payload.name != project.name:
                changed_fields["name"] = {"from": project.name, "to": payload.name}
            project.name = payload.name
        if "description" in payload.model_fields_set:
            if payload.description != project.description:
                changed_fields["description"] = {
                    "from": project.description,
                    "to": payload.description,
                }
            project.description = payload.description
        if payload.is_active is not None:
            if payload.is_active != project.is_active:
                changed_fields["is_active"] = {"from": project.is_active, "to": payload.is_active}
            project.is_active = payload.is_active
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ProjectSlugAlreadyExistsError from exc
        action = (
            "project.reactivated"
            if changed_fields.get("is_active", {}).get("to") is True
            else "project.deactivated"
            if changed_fields.get("is_active", {}).get("to") is False
            else "project.updated"
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action=action,
            message=f"Updated project {project.name}.",
            team_id=project.team_id,
            project_id=project.id,
            metadata={
                "project_id": str(project.id),
                "team_id": str(project.team_id),
                "changed_fields": changed_fields,
            },
            db=db,
        )
    logger.info(
        "project_updated",
        project_id=str(project.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return await _to_project_response(project, db=db)


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
            metadata={"project_id": str(project.id), "team_id": str(project.team_id)},
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
    if not org_settings.allow_secret_copy:
        raise SecretDeliveryDisabledError
    async with transaction(db):
        project = await _get_active_project(project_id=project_id, scope=scope, db=db)
        await teams_facade.ensure_team_active(team_id=project.team_id, scope=scope, db=db)
        access_summary = await _build_effective_access_summary(
            project=project, virtual_key=None, db=db
        )
        if not access_summary.is_usable:
            if access_summary.blocking_code == "no_effective_access_policy":
                raise PolicyNotConfiguredError(access_summary)
            raise ProjectAccessUnavailableError(access_summary)
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
            created_by=actor.id,
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
            metadata={
                "virtual_key_id": str(virtual_key.id),
                "project_id": str(project.id),
                "team_id": str(project.team_id),
                "name": virtual_key.name,
                "key_prefix": virtual_key.key_prefix,
                "expires_at": virtual_key.expires_at.isoformat()
                if virtual_key.expires_at
                else None,
            },
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
        key=raw_key,
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


async def list_virtual_key_inventory(
    *,
    scope: Scope,
    visible_team_ids: set[UUID] | None,
    visible_project_ids: set[UUID] | None,
    manageable_team_ids: set[UUID],
    manageable_project_ids: set[UUID],
    can_manage_all: bool,
    team_id: UUID | None,
    project_id: UUID | None,
    status: str | None,
    search: str | None,
    usage: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> VirtualKeyInventoryPage:
    derived_status_filter = status in {
        "active",
        "no_effective_access",
        "expiring_soon",
        "unused",
    }
    if derived_status_filter:
        return await _list_virtual_key_inventory_with_derived_status(
            scope=scope,
            visible_team_ids=visible_team_ids,
            visible_project_ids=visible_project_ids,
            manageable_team_ids=manageable_team_ids,
            manageable_project_ids=manageable_project_ids,
            can_manage_all=can_manage_all,
            team_id=team_id,
            project_id=project_id,
            status=status,
            search=search,
            usage=usage,
            limit=limit,
            offset=offset,
            db=db,
        )

    rows, total = await repository.list_virtual_key_inventory(
        org_id=scope.org_id,
        team_ids=visible_team_ids,
        project_ids=visible_project_ids,
        team_id=team_id,
        project_id=project_id,
        status=status,
        search=search,
        usage=usage,
        limit=limit,
        offset=offset,
        db=db,
    )
    items = await _inventory_items_from_rows(
        rows=rows,
        manageable_team_ids=manageable_team_ids,
        manageable_project_ids=manageable_project_ids,
        can_manage_all=can_manage_all,
        db=db,
    )
    return VirtualKeyInventoryPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


async def _list_virtual_key_inventory_with_derived_status(
    *,
    scope: Scope,
    visible_team_ids: set[UUID] | None,
    visible_project_ids: set[UUID] | None,
    manageable_team_ids: set[UUID],
    manageable_project_ids: set[UUID],
    can_manage_all: bool,
    team_id: UUID | None,
    project_id: UUID | None,
    status: str,
    search: str | None,
    usage: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> VirtualKeyInventoryPage:
    rows, _ = await repository.list_virtual_key_inventory(
        org_id=scope.org_id,
        team_ids=visible_team_ids,
        project_ids=visible_project_ids,
        team_id=team_id,
        project_id=project_id,
        status=status,
        search=search,
        usage=usage,
        limit=None,
        offset=0,
        db=db,
    )
    items = await _inventory_items_from_rows(
        rows=rows,
        manageable_team_ids=manageable_team_ids,
        manageable_project_ids=manageable_project_ids,
        can_manage_all=can_manage_all,
        db=db,
    )
    matching_items = [item for item in items if item.status == status]

    return VirtualKeyInventoryPage(
        items=matching_items[offset : offset + limit],
        total=len(matching_items),
        limit=limit,
        offset=offset,
    )


async def _inventory_items_from_rows(
    *,
    rows: list[tuple[VirtualKey, Project, Team, User | None]],
    manageable_team_ids: set[UUID],
    manageable_project_ids: set[UUID],
    can_manage_all: bool,
    db: AsyncSession,
) -> list[VirtualKeyInventoryItem]:
    routing_ready = await _batch_inventory_routing_readiness(rows=rows, db=db)
    return [
        _to_inventory_item(
            virtual_key=virtual_key,
            project=project,
            team=team,
            creator=creator,
            can_manage=(
                can_manage_all
                or team.id in manageable_team_ids
                or project.id in manageable_project_ids
            ),
            routing_ready=routing_ready.get(virtual_key.id, False),
        )
        for virtual_key, project, team, creator in rows
    ]


async def _batch_inventory_routing_readiness(
    *,
    rows: list[tuple[VirtualKey, Project, Team, User | None]],
    db: AsyncSession,
) -> dict[UUID, bool]:
    if not rows:
        return {}
    org_id = rows[0][0].org_id
    team_ids = {team.id for _key, _project, team, _creator in rows}
    project_ids = {project.id for _key, project, _team, _creator in rows}
    key_ids = {key.id for key, _project, _team, _creator in rows}
    assignments = list(
        await db.scalars(
            select(PolicyAssignment).where(
                PolicyAssignment.org_id == org_id,
                PolicyAssignment.policy_type == "access",
                PolicyAssignment.is_active.is_(True),
                or_(
                    PolicyAssignment.scope_type == "org",
                    PolicyAssignment.team_id.in_(team_ids),
                    PolicyAssignment.project_id.in_(project_ids),
                    PolicyAssignment.virtual_key_id.in_(key_ids),
                ),
            )
        )
    )
    policy_ids = {item.policy_id for item in assignments}
    policies = {
        policy.policy_id: policy
        for policy in await db.scalars(
            select(AccessPolicy).where(
                AccessPolicy.org_id == org_id,
                AccessPolicy.policy_id.in_(policy_ids),
                AccessPolicy.is_active.is_(True),
            )
        )
    }
    shared_policy_id_by_concrete_policy_id = {
        policy.id: shared_policy_id for shared_policy_id, policy in policies.items()
    }
    public_models = list(
        await db.scalars(
            select(AccessPolicyPublicModel).where(
                AccessPolicyPublicModel.org_id == org_id,
                AccessPolicyPublicModel.access_policy_id.in_(
                    {policy.id for policy in policies.values()}
                ),
                AccessPolicyPublicModel.is_active.is_(True),
            )
        )
    )
    public_model_ids = {public_model.id for public_model in public_models}
    candidates = list(
        await db.scalars(
            select(AccessPolicyRouteCandidate).where(
                AccessPolicyRouteCandidate.org_id == org_id,
                AccessPolicyRouteCandidate.public_model_id.in_(public_model_ids),
                AccessPolicyRouteCandidate.is_active.is_(True),
            )
        )
    )
    pool_ids = {candidate.credential_pool_id for candidate in candidates}
    model_ids = {candidate.model_offering_id for candidate in candidates}
    pools = {
        pool.id: pool
        for pool in await db.scalars(
            select(CredentialPool).where(
                CredentialPool.org_id == org_id,
                CredentialPool.id.in_(pool_ids),
                CredentialPool.is_active.is_(True),
            )
        )
    }
    models = {
        model.id: model
        for model in await db.scalars(
            select(ModelOffering).where(
                ModelOffering.org_id == org_id,
                ModelOffering.id.in_(model_ids),
                ModelOffering.is_active.is_(True),
            )
        )
    }
    ready_pool_ids = set(
        await db.scalars(
            select(CredentialPoolCredential.pool_id)
            .join(
                ProviderCredential,
                ProviderCredential.id == CredentialPoolCredential.provider_credential_id,
            )
            .where(
                CredentialPoolCredential.org_id == org_id,
                CredentialPoolCredential.pool_id.in_(pool_ids),
                CredentialPoolCredential.is_active.is_(True),
                ProviderCredential.is_active.is_(True),
            )
            .distinct()
        )
    )
    shared_policy_id_by_public_model_id = {
        public_model.id: shared_policy_id_by_concrete_policy_id[public_model.access_policy_id]
        for public_model in public_models
        if public_model.access_policy_id in shared_policy_id_by_concrete_policy_id
    }
    candidates_by_policy: dict[UUID, set[tuple[UUID, UUID, UUID]]] = {}
    for candidate in candidates:
        policy_id = shared_policy_id_by_public_model_id.get(candidate.public_model_id)
        if policy_id is None:
            continue
        signatures = candidates_by_policy.setdefault(policy_id, set())
        pool = pools.get(candidate.credential_pool_id)
        if pool is None or candidate.credential_pool_id not in ready_pool_ids:
            continue
        model = models.get(candidate.model_offering_id)
        if (
            model is not None
            and model.provider_id == candidate.provider_id
            and pool.provider_id == candidate.provider_id
        ):
            signatures.add(
                (candidate.provider_id, candidate.credential_pool_id, candidate.model_offering_id)
            )

    scope_order = ("org", "team", "project", "virtual_key")
    readiness: dict[UUID, bool] = {}
    for key, project, team, _creator in rows:
        effective: set[tuple[UUID, UUID, UUID]] | None = None
        for scope_type in scope_order:
            scoped_assignments = [
                assignment
                for assignment in assignments
                if assignment.scope_type == scope_type
                and (
                    scope_type == "org"
                    or (scope_type == "team" and assignment.team_id == team.id)
                    or (scope_type == "project" and assignment.project_id == project.id)
                    or (scope_type == "virtual_key" and assignment.virtual_key_id == key.id)
                )
            ]
            candidates = set().union(
                *(
                    candidates_by_policy.get(assignment.policy_id, set())
                    for assignment in scoped_assignments
                    if assignment.policy_id in policies
                )
            )
            if not candidates:
                continue
            effective = candidates if effective is None else candidates & effective
        readiness[key.id] = bool(effective)
    return readiness


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


async def rotate_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: RotateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    if not org_settings.allow_secret_copy:
        raise SecretDeliveryDisabledError
    async with transaction(db):
        project = await _get_active_project(project_id=project_id, scope=scope, db=db)
        await teams_facade.ensure_team_active(team_id=project.team_id, scope=scope, db=db)
        old_key = await _get_virtual_key_or_raise(
            project_id=project_id, key_id=key_id, scope=scope, db=db
        )
        if old_key.revoked_at is not None:
            raise VirtualKeyAlreadyRevokedError
        raw_key = generate_virtual_key(prefix=org_settings.virtual_key_prefix)
        expires_at = payload.expires_at
        if expires_at is None and org_settings.default_virtual_key_expiration_days is not None:
            expires_at = datetime.now(UTC) + timedelta(
                days=org_settings.default_virtual_key_expiration_days
            )
        new_key = await repository.create_virtual_key(
            org_id=scope.org_id,
            project_id=project.id,
            name=payload.name or f"{old_key.name} replacement",
            key_hash=hash_token(raw_key),
            key_prefix=_key_prefix(raw_key),
            created_by=actor.id,
            expires_at=expires_at,
            supersedes_key_id=old_key.id,
            db=db,
        )
        old_key.deprecated_at = datetime.now(UTC) + timedelta(days=payload.overlap_days)
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.created",
            message=f"Created replacement virtual key {new_key.name}.",
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=new_key.id,
            metadata={
                "virtual_key_id": str(new_key.id),
                "supersedes_key_id": str(old_key.id),
                "key_prefix": new_key.key_prefix,
            },
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.deprecated",
            message=f"Deprecated virtual key {old_key.name} for rotation.",
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=old_key.id,
            metadata={
                "virtual_key_id": str(old_key.id),
                "successor_key_id": str(new_key.id),
                "deprecated_at": old_key.deprecated_at.isoformat(),
            },
            db=db,
        )
    response = await _to_virtual_key_response(new_key, project=project, scope=scope, db=db)
    return CreatedVirtualKeyResponse(**response.model_dump(), key=raw_key)


async def get_project_archive_impact(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProjectArchiveImpactResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    since = datetime.now(UTC) - timedelta(days=IMPACT_USAGE_WINDOW_DAYS)
    request_count, cost_cents = await repository.summarize_recent_usage(
        org_id=scope.org_id,
        since=since,
        team_id=None,
        project_id=project_id,
        virtual_key_id=None,
        db=db,
    )
    return ProjectArchiveImpactResponse(
        active_virtual_key_count=await repository.count_active_project_virtual_keys(
            org_id=scope.org_id,
            project_id=project_id,
            db=db,
        ),
        recent_usage_window_days=IMPACT_USAGE_WINDOW_DAYS,
        recent_request_count=request_count,
        recent_cost_cents=cost_cents,
        effective_access=await _build_effective_access_summary(
            project=project,
            virtual_key=None,
            db=db,
        ),
    )


async def get_virtual_key_revoke_impact(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyRevokeImpactResponse:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_key = await _get_virtual_key_or_raise(
        project_id=project_id,
        key_id=key_id,
        scope=scope,
        db=db,
    )
    since = datetime.now(UTC) - timedelta(days=IMPACT_USAGE_WINDOW_DAYS)
    request_count, cost_cents = await repository.summarize_recent_usage(
        org_id=scope.org_id,
        since=since,
        team_id=None,
        project_id=None,
        virtual_key_id=key_id,
        db=db,
    )
    effective_access = await _build_effective_access_summary(
        project=project,
        virtual_key=virtual_key,
        db=db,
    )
    return VirtualKeyRevokeImpactResponse(
        last_used_at=virtual_key.last_used_at,
        recent_usage_window_days=IMPACT_USAGE_WINDOW_DAYS,
        recent_request_count=request_count,
        recent_cost_cents=cost_cents,
        effective_access=effective_access,
        already_unusable_reason=effective_access.blocking_reason
        if not effective_access.is_usable
        else None,
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
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        changed_fields: dict[str, dict[str, object]] = {}
        if payload.name is not None:
            if payload.name != virtual_key.name:
                changed_fields["name"] = {"from": virtual_key.name, "to": payload.name}
            virtual_key.name = payload.name
        if "expires_at" in payload.model_fields_set:
            if payload.expires_at != virtual_key.expires_at:
                changed_fields["expires_at"] = {
                    "from": virtual_key.expires_at.isoformat() if virtual_key.expires_at else None,
                    "to": payload.expires_at.isoformat() if payload.expires_at else None,
                }
            virtual_key.expires_at = payload.expires_at
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.updated",
            message=f"Updated virtual key {virtual_key.name}.",
            team_id=project.team_id,
            project_id=project_id,
            virtual_key_id=virtual_key.id,
            metadata={
                "virtual_key_id": str(virtual_key.id),
                "project_id": str(project_id),
                "team_id": str(project.team_id),
                "changed_fields": changed_fields,
            },
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
    reason: str,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    force: bool = False,
) -> None:
    reason = reason.strip()
    if not reason:
        raise ValueError("revocation reason must not be empty")
    if len(reason) > 500:
        raise ValueError("revocation reason must be at most 500 characters")
    async with transaction(db):
        project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
        virtual_key = await _get_virtual_key_or_raise(
            project_id=project_id,
            key_id=key_id,
            scope=scope,
            db=db,
        )
        if virtual_key.revoked_at is not None:
            raise VirtualKeyAlreadyRevokedError
        if (
            virtual_key.deprecated_at is not None
            and _as_utc(virtual_key.deprecated_at) > datetime.now(UTC)
            and not force
        ):
            raise VirtualKeyOverlapActiveError(virtual_key.deprecated_at)
        virtual_key.revoked_at = datetime.now(UTC)
        virtual_key.revoked_by = actor.id
        virtual_key.revoked_reason = reason
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="virtual_key.revoked",
            message=f"Revoked virtual key {virtual_key.name}.",
            team_id=project.team_id,
            project_id=project_id,
            virtual_key_id=virtual_key.id,
            metadata={
                "virtual_key_id": str(virtual_key.id),
                "project_id": str(project_id),
                "team_id": str(project.team_id),
                "revoked_by": str(actor.id),
                "revoked_at": virtual_key.revoked_at.isoformat(),
                "reason": reason,
            },
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
    plan = await resolve_access_plan(payload=payload, db=db)
    primary = plan.attempts[0]
    return ResolvedAccess(
        org_id=primary.org_id,
        team_id=primary.team_id,
        project_id=primary.project_id,
        access_policy_id=primary.access_policy_id,
        access_policy_revision_id=primary.access_policy_revision_id,
        access_policy_assignment_id=primary.access_policy_assignment_id,
        access_policy_route_id=primary.access_policy_route_id,
        public_model_id=primary.public_model_id,
        route_candidate_id=primary.route_candidate_id,
        primary_route_candidate_id=primary.primary_route_candidate_id,
        public_model_name=primary.public_model_name,
        routing_mode=primary.routing_mode,
        model_offering_id=primary.model_offering_id,
        limit_policy_ids=primary.limit_policy_ids,
        limit_policies=primary.limit_policies,
        virtual_key_id=primary.virtual_key_id,
        provider_id=primary.provider_id,
        pool_id=primary.pool_id,
        provider_key_id=primary.provider_key_id,
        requested_model=primary.requested_model,
        provider_model=primary.provider_model,
        input_price_per_million_tokens=primary.input_price_per_million_tokens,
        output_price_per_million_tokens=primary.output_price_per_million_tokens,
        fallback_disabled_reason=plan.fallback_disabled_reason,
    )


async def resolve_key_subject(
    *,
    payload: ResolveKeySubjectRequest,
    db: AsyncSession,
) -> ResolvedKeySubject:
    virtual_key, project = await _resolve_key_project(
        raw_key=payload.raw_key,
        db=db,
    )
    team = await db.get(Team, project.team_id)
    return ResolvedKeySubject(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        virtual_key_name=virtual_key.name,
        project_name=project.name,
        team_name=team.name if team else None,
    )


async def resolve_access_plan(
    *,
    payload: ResolveAccessRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    subject = await resolve_key_subject(
        payload=ResolveKeySubjectRequest(raw_key=payload.raw_key),
        db=db,
    )
    return await resolve_access_plan_for_subject(
        payload=ResolveAccessPlanForSubjectRequest(
            subject=subject,
            requested_model=payload.requested_model,
            provider_id=payload.provider_id,
            streaming=payload.streaming,
            gateway_endpoint=payload.gateway_endpoint,
        ),
        db=db,
    )


async def resolve_access_plan_for_subject(
    *,
    payload: ResolveAccessPlanForSubjectRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    subject = payload.subject
    virtual_key = await repository.get_virtual_key(
        org_id=subject.org_id,
        project_id=subject.project_id,
        key_id=subject.virtual_key_id,
        db=db,
    )
    project = await repository.get_project(
        project_id=subject.project_id,
        org_id=subject.org_id,
        db=db,
    )
    if virtual_key is None or project is None or project.team_id != subject.team_id:
        raise InvalidVirtualKeyError
    return await _build_resolved_access_plan(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        streaming=payload.streaming,
        db=db,
    )


async def resolve_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    virtual_key, project = await _resolve_key_project_readonly(
        org_id=org_id,
        virtual_key_id=payload.virtual_key_id,
        db=db,
    )
    return await _build_resolved_access_plan(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        streaming=payload.streaming,
        db=db,
    )


async def explain_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlanExplanation:
    virtual_key, project = await _resolve_key_project_readonly(
        org_id=org_id,
        virtual_key_id=payload.virtual_key_id,
        db=db,
    )
    plan: ResolvedAccessPlan | None = None
    access_denied_reason: str | None = None
    try:
        plan = await _build_resolved_access_plan(
            virtual_key=virtual_key,
            project=project,
            requested_model=payload.requested_model,
            provider_id=payload.provider_id,
            gateway_endpoint=payload.gateway_endpoint,
            streaming=payload.streaming,
            db=db,
        )
    except AccessDeniedError:
        access_denied_reason = "no_matching_route"
    candidates = await _explain_route_candidates(
        virtual_key=virtual_key,
        project=project,
        requested_model=payload.requested_model,
        provider_id=payload.provider_id,
        gateway_endpoint=payload.gateway_endpoint,
        plan=plan,
        db=db,
    )
    return ResolvedAccessPlanExplanation(
        plan=plan,
        candidates=candidates,
        access_denied_reason=access_denied_reason,
    )


async def _build_resolved_access_plan(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    streaming: bool,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    matched = await _match_policy_route(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        requested_model=requested_model,
        provider_id=provider_id,
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    if not matched:
        raise AccessDeniedError
    public_model = matched[0][0]
    primary_candidate = matched[0][1]
    attempts: list[ResolvedRouteAttempt] = []
    attempt_limit_rules: list[list[tuple[LimitPolicyRule, LimitPolicy, UUID]]] = []
    for index, (
        attempt_public_model,
        attempt_candidate,
        attempt_assignment,
        attempt_model,
        attempt_pool,
        _provider_id,
        _provider_model,
        _input_price,
        _output_price,
    ) in enumerate(matched):
        limit_rules = await _matching_limit_policies(
            org_id=virtual_key.org_id,
            team_id=project.team_id,
            project_id=project.id,
            virtual_key_id=virtual_key.id,
            public_model=attempt_public_model,
            candidate=attempt_candidate,
            db=db,
        )
        attempt_limit_rules.append(limit_rules)
        attempts.append(
            _to_resolved_route_attempt(
                virtual_key=virtual_key,
                project=project,
                requested_model=requested_model,
                public_model=attempt_public_model,
                candidate=attempt_candidate,
                assignment=attempt_assignment,
                model=attempt_model,
                pool=attempt_pool,
                attempt_index=index,
                primary_route_candidate_id=primary_candidate.id,
                limit_rules=limit_rules,
            )
        )
    fallback_disabled_reason = None
    if provider_id is not None and len(attempts) == 1:
        fallback_disabled_reason = "provider_pinned"
    if streaming and len(attempts) > 1:
        attempts = attempts[:1]
        fallback_disabled_reason = "streaming_fallback_phase_2"
    plan_limit_rules = attempt_limit_rules[0] if attempt_limit_rules else []
    return ResolvedAccessPlan(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        requested_model=requested_model,
        public_model_name=public_model.public_model_name,
        routing_mode=public_model.routing_mode,
        fallback_on=public_model.fallback_on,
        max_route_attempts=public_model.max_route_attempts,
        provider_pinned=provider_id is not None,
        fallback_disabled_reason=fallback_disabled_reason,
        limit_policy_ids=list({policy.id for _rule, policy, _assignment_id in plan_limit_rules}),
        limit_policies=[
            _to_resolved_limit_policy(rule, policy, assignment_id)
            for rule, policy, assignment_id in plan_limit_rules
        ],
        attempts=attempts,
    )


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    virtual_key, project = await _resolve_key_project(
        raw_key=raw_key,
        db=db,
    )
    models: list[AccessibleModel] = []
    by_id: dict[str, AccessibleModel] = {}
    for public_model, candidate, assignment in await build_effective_access_routes_readonly(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    ):
        routable = await _routable_route_candidate(
            org_id=virtual_key.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        provider = await db.get(Provider, model.provider_id)
        policy_id = assignment.policy_id
        policy_name = (
            (
                await _access_policy_names(
                    org_id=virtual_key.org_id,
                    policy_ids=[policy_id],
                    db=db,
                )
            ).get(policy_id)
            if policy_id is not None
            else None
        )
        model_id = _accessible_model_id(public_model=public_model, candidate=candidate, model=model)
        candidate_metadata = _accessible_model_candidate(
            candidate=candidate,
            model=model,
            pool=pool,
            provider=provider,
        )
        if model_id in by_id:
            by_id[model_id].candidates.append(candidate_metadata)
            continue
        accessible = AccessibleModel(
            id=model_id,
            owned_by=model.provider_id.hex,
            provider_id=model.provider_id,
            provider_name=provider.name if provider else "Unknown provider",
            model_offering_id=model.id,
            access_policy_id=policy_id,
            access_policy_name=policy_name,
            access_policy_route_id=None,
            public_model_id=public_model.id,
            route_candidate_id=candidate.id,
            public_model_name=public_model.public_model_name,
            routing_mode=public_model.routing_mode,
            pool_id=pool.id,
            pool_name=pool.name,
            source_scope=assignment.scope_type,
            candidates=[candidate_metadata],
        )
        by_id[model_id] = accessible
        models.append(accessible)
    return models


async def list_project_accessible_models(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[AccessibleModel]:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None or not project.is_active:
        raise ProjectNotFoundError
    models: list[AccessibleModel] = []
    seen: set[tuple[UUID, UUID]] = set()
    for public_model, candidate, assignment in await build_effective_access_routes_readonly(
        org_id=scope.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=None,
        db=db,
    ):
        routable = await _routable_route_candidate(
            org_id=scope.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        provider = await db.get(Provider, model.provider_id)
        policy_id = assignment.policy_id
        policy_name = (
            (
                await _access_policy_names(
                    org_id=scope.org_id,
                    policy_ids=[policy_id],
                    db=db,
                )
            ).get(policy_id)
            if policy_id is not None
            else None
        )
        dedupe_key = (public_model.id, candidate.id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        models.append(
            AccessibleModel(
                id=_accessible_model_id(
                    public_model=public_model,
                    candidate=candidate,
                    model=model,
                ),
                owned_by=model.provider_id.hex,
                provider_id=model.provider_id,
                provider_name=provider.name if provider else "Unknown provider",
                model_offering_id=model.id,
                access_policy_id=policy_id,
                access_policy_name=policy_name,
                access_policy_route_id=None,
                public_model_id=public_model.id,
                route_candidate_id=candidate.id,
                public_model_name=public_model.public_model_name,
                routing_mode=public_model.routing_mode,
                pool_id=pool.id,
                pool_name=pool.name,
                source_scope=assignment.scope_type,
            )
        )
    return sorted(models, key=lambda item: (item.id, str(item.provider_id)))


async def get_project_effective_access(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    return await _build_effective_access_summary(project=project, virtual_key=None, db=db)


async def get_virtual_key_effective_access(
    *, project_id: UUID, key_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    virtual_key = await _get_virtual_key_or_raise(
        project_id=project_id, key_id=key_id, scope=scope, db=db
    )
    return await _build_effective_access_summary(project=project, virtual_key=virtual_key, db=db)


async def _build_effective_access_summary(
    *, project: Project, virtual_key: VirtualKey | None, db: AsyncSession
) -> EffectiveAccessSummary:
    organization = await repository.get_organization(org_id=project.org_id, db=db)
    try:
        team = await teams_facade.get_team(
            team_id=project.team_id, scope=Scope(org_id=project.org_id), db=db
        )
        team_active = team.is_active
    except TeamNotFoundError:
        team_active = False
    organization_active = bool(organization and organization.is_active)
    key_active = None
    blocker: tuple[str, str] | None = None
    if virtual_key is not None:
        expired = virtual_key.expires_at is not None and _as_utc(
            virtual_key.expires_at
        ) <= datetime.now(UTC)
        key_active = virtual_key.revoked_at is None and not expired
        if virtual_key.revoked_at is not None:
            blocker = ("key_revoked", "The virtual key has been revoked.")
        elif expired:
            blocker = ("key_expired", "The virtual key has expired.")
    if blocker is None and not organization_active:
        blocker = ("organization_inactive", "The organization is inactive.")
    if blocker is None and not team_active:
        blocker = ("team_archived", "The owning team is archived.")
    if blocker is None and not project.is_active:
        blocker = ("project_archived", "The project is archived.")

    routes = await build_effective_access_routes_readonly(
        org_id=project.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id if virtual_key else None,
        db=db,
    )
    routable_routes: list[EffectiveRouteSummary] = []
    policy_names = await _access_policy_names(
        org_id=project.org_id,
        policy_ids=list(
            {
                assignment.policy_id
                for public_model, _candidate, assignment in routes
            }
        ),
        db=db,
    )
    for public_model, candidate, assignment in routes:
        routable = await _routable_route_candidate(
            org_id=project.org_id,
            candidate=candidate,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        routable_routes.append(
            EffectiveRouteSummary(
                provider_id=candidate.provider_id,
                credential_pool_id=candidate.credential_pool_id,
                model_offering_id=model.id,
                public_model_id=public_model.id,
                route_candidate_id=candidate.id,
                public_model_name=public_model.public_model_name,
                routing_mode=public_model.routing_mode,
                provider_model=model.provider_model_name,
                access_policy_id=assignment.policy_id,
                access_policy_revision_id=public_model.policy_revision_id,
                access_policy_name=policy_names.get(
                    assignment.policy_id
                ),
                access_policy_assignment_id=assignment.id,
                source_scope=assignment.scope_type,
            )
        )

    route_assignments = list(
        {assignment.id: assignment for _public_model, _candidate, assignment in routes}.values()
    )
    access_references = await _effective_access_policy_references(
        org_id=project.org_id, assignments=route_assignments, db=db
    )
    access_reference = access_references[0] if access_references else None
    if blocker is None and access_reference is None:
        blocker = ("no_effective_access_policy", "No effective active access policy applies.")
    elif blocker is None and not routable_routes:
        blocker = (
            "no_routable_provider_model",
            "The effective policy has no currently routable provider and model.",
        )
    limits = await _effective_limit_policy_references(
        org_id=project.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id if virtual_key else None,
        db=db,
    )
    return EffectiveAccessSummary(
        is_usable=blocker is None,
        blocking_code=blocker[0] if blocker else None,
        blocking_reason=blocker[1] if blocker else None,
        ownership=OwnershipChainState(
            organization_active=organization_active,
            team_active=team_active,
            project_active=project.is_active,
            key_active=key_active,
        ),
        access_policy=access_reference,
        access_policies=access_references,
        routes=routable_routes,
        limit_policies=limits,
    )


async def _resolve_key_project(*, raw_key: str, db: AsyncSession) -> ResolvedKeyProject:
    virtual_key = await repository.get_virtual_key_by_hash(key_hash=hash_token(raw_key), db=db)
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    try:
        await _ensure_organization_active(org_id=virtual_key.org_id, db=db)
    except OrganizationInactiveError as exc:
        raise InvalidVirtualKeyError from exc
    project = await repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError
    try:
        await teams_facade.ensure_team_active(
            team_id=project.team_id,
            scope=Scope(org_id=virtual_key.org_id),
            db=db,
        )
    except (TeamInactiveError, TeamNotFoundError) as exc:
        raise InvalidVirtualKeyError from exc
    virtual_key.last_used_at = datetime.now(UTC)
    await db.flush()
    return virtual_key, project


async def _resolve_key_project_readonly(
    *,
    org_id: UUID,
    virtual_key_id: UUID,
    db: AsyncSession,
) -> ResolvedKeyProject:
    virtual_key = await repository.get_virtual_key_by_id(
        org_id=org_id,
        key_id=virtual_key_id,
        db=db,
    )
    if virtual_key is None:
        raise InvalidVirtualKeyError
    if virtual_key.revoked_at is not None:
        raise InvalidVirtualKeyError
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        raise InvalidVirtualKeyError

    try:
        await _ensure_organization_active(org_id=virtual_key.org_id, db=db)
    except OrganizationInactiveError as exc:
        raise InvalidVirtualKeyError from exc
    project = await repository.get_project(
        project_id=virtual_key.project_id,
        org_id=virtual_key.org_id,
        db=db,
    )
    if project is None or not project.is_active:
        raise InvalidVirtualKeyError
    try:
        await teams_facade.ensure_team_active(
            team_id=project.team_id,
            scope=Scope(org_id=virtual_key.org_id),
            db=db,
        )
    except (TeamInactiveError, TeamNotFoundError) as exc:
        raise InvalidVirtualKeyError from exc
    return virtual_key, project


async def _ensure_organization_active(*, org_id: UUID, db: AsyncSession) -> None:
    organization = await repository.get_organization(org_id=org_id, db=db)
    if organization is None or not organization.is_active:
        raise OrganizationInactiveError


async def _get_active_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    await _ensure_organization_active(org_id=scope.org_id, db=db)
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    if not project.is_active:
        raise ProjectInactiveError
    return project


async def _routable_route_candidate(
    *,
    org_id: UUID,
    candidate: AccessPolicyRouteCandidate,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
):
    try:
        provider = await providers_facade.get_provider(
            provider_id=candidate.provider_id,
            scope=Scope(org_id=org_id),
            db=db,
        )
        pool = await providers_facade.get_credential_pool(
            pool_id=candidate.credential_pool_id,
            scope=Scope(org_id=org_id),
            db=db,
        )
        model = await providers_facade.get_model_offering(
            model_offering_id=candidate.provider_model_offering_id or candidate.model_offering_id,
            scope=Scope(org_id=org_id),
            db=db,
        )
        credentials = await providers_facade.list_credential_pool_credentials(
            provider_id=candidate.provider_id,
            pool_id=candidate.credential_pool_id,
            scope=Scope(org_id=org_id),
            db=db,
        )
    except ProviderNotFoundError:
        return None
    if (
        not _provider_supports_gateway_endpoint(provider, gateway_endpoint)
        or not pool.is_active
        or not model.is_active
        or pool.provider_id != candidate.provider_id
        or model.provider_id != candidate.provider_id
        or not any(item.is_active and item.credential.is_active for item in credentials)
    ):
        return None
    return pool, model


async def _match_policy_route(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    requested_model: str,
    provider_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
) -> list[ResolvedPolicyRoute]:
    candidates = await build_effective_access_routes_readonly(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    candidates.sort(key=lambda item: (item[1].priority, -item[1].weight, item[1].created_at))
    matches: list[ResolvedPolicyRoute] = []
    matched_public_model_id: UUID | None = None
    for public_model, candidate, assignment in candidates:
        if matched_public_model_id is not None and public_model.id != matched_public_model_id:
            continue
        if provider_id is not None and candidate.provider_id != provider_id:
            continue
        routable = await _routable_route_candidate(
            org_id=org_id,
            candidate=candidate,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        if requested_model != public_model.public_model_name:
            continue
        matched_public_model_id = public_model.id
        matches.append(
            (
                public_model,
                candidate,
                assignment,
                model,
                pool,
                model.provider_id,
                model.provider_model_name,
                model.effective_input_price_per_million_tokens,
                model.effective_output_price_per_million_tokens,
            )
        )
        if public_model.routing_mode == "single_route":
            break
        if (
            public_model.max_route_attempts is not None
            and len(matches) >= public_model.max_route_attempts
        ):
            break
    return matches


async def _explain_route_candidates(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    plan: ResolvedAccessPlan | None,
    db: AsyncSession,
) -> list[RouteCandidateExplanation]:
    candidates = await build_effective_access_routes_readonly(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    )
    candidates.sort(key=lambda item: (item[1].priority, -item[1].weight, item[1].created_at))
    attempt_index_by_candidate = {
        attempt.route_candidate_id: attempt.routing_attempt_index for attempt in plan.attempts
    } if plan is not None else {}
    selected_candidate_id = plan.attempts[0].route_candidate_id if plan and plan.attempts else None
    explanations: list[RouteCandidateExplanation] = []
    for candidate_index, (public_model, candidate, assignment) in enumerate(candidates):
        provider = await db.get(Provider, candidate.provider_id)
        pool = await db.get(CredentialPool, candidate.credential_pool_id)
        model_id = candidate.provider_model_offering_id or candidate.model_offering_id
        model = await db.get(ModelOffering, model_id)
        attempt_index = attempt_index_by_candidate.get(candidate.id)
        skipped_reason, skipped_message = _route_candidate_skip_reason(
            public_model=public_model,
            candidate=candidate,
            provider=provider,
            pool=pool,
            model=model,
            requested_model=requested_model,
            provider_id=provider_id,
            gateway_endpoint=gateway_endpoint,
            plan=plan,
            attempt_index=attempt_index,
        )
        explanations.append(
            RouteCandidateExplanation(
                candidate_index=candidate_index,
                route_candidate_id=candidate.id,
                public_model_id=public_model.id,
                public_model_name=public_model.public_model_name,
                access_policy_id=assignment.policy_id,
                access_policy_revision_id=public_model.policy_revision_id,
                assignment_id=assignment.id,
                provider_id=candidate.provider_id,
                provider_name=provider.name if provider else None,
                credential_pool_id=candidate.credential_pool_id,
                credential_pool_name=pool.name if pool else None,
                provider_model_offering_id=model_id,
                provider_model=model.provider_model_name if model else None,
                attempt_index=attempt_index,
                selected=candidate.id == selected_candidate_id,
                would_attempt=attempt_index is not None,
                skipped_reason=skipped_reason,
                skipped_message=skipped_message,
            )
        )
    return explanations


def _route_candidate_skip_reason(
    *,
    public_model: AccessPolicyPublicModel,
    candidate: AccessPolicyRouteCandidate,
    provider: Provider | None,
    pool: CredentialPool | None,
    model: ModelOffering | None,
    requested_model: str,
    provider_id: UUID | None,
    gateway_endpoint: str | None,
    plan: ResolvedAccessPlan | None,
    attempt_index: int | None,
) -> tuple[str | None, str | None]:
    if attempt_index is not None:
        return None, None
    if requested_model != public_model.public_model_name:
        return "requested_model_mismatch", "The public model name did not match the request."
    if provider_id is not None and candidate.provider_id != provider_id:
        return "provider_pinned_mismatch", "The request pinned a different provider."
    if provider is None or not provider.is_active:
        return "provider_inactive", "The provider is inactive or missing."
    if pool is None or not pool.is_active:
        return "credential_pool_inactive", "The credential pool is inactive or missing."
    if model is None or not model.is_active or model.provider_id != candidate.provider_id:
        return "provider_model_offering_inactive", "The model offering is inactive or missing."
    if pool.provider_id != candidate.provider_id:
        return "credential_pool_inactive", "The credential pool belongs to a different provider."
    if not _provider_supports_gateway_endpoint(provider, gateway_endpoint):
        return "endpoint_incompatible", "The provider does not support this gateway endpoint."
    if plan is not None and public_model.public_model_name == plan.public_model_name:
        return (
            "routing_mode_disables_fallback",
            "The selected routing mode did not attempt this route.",
        )
    return "child_scope_narrowing_removed_candidate", "A narrower access scope removed this route."


def _provider_supports_gateway_endpoint(provider, gateway_endpoint: str | None) -> bool:
    if gateway_endpoint is None:
        return True
    if gateway_endpoint == "anthropic_messages":
        return bool(provider.integration_capabilities.get("native_anthropic_messages"))
    if gateway_endpoint in {"chat_completions", "responses", "completions"}:
        return bool(provider.integration_capabilities.get("openai_compatible_chat"))
    return True


async def build_effective_access_routes_readonly(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[EffectiveAccessRouteCandidate]:
    assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="access",
        db=db,
    )
    effective: list[EffectiveAccessRouteCandidate] | None = None
    for scope_type in ("org", "team", "project", "virtual_key"):
        scoped = [assignment for assignment in assignments if assignment.scope_type == scope_type]
        if not scoped:
            # No access assignment at this scope: inherit the ancestor set unchanged.
            continue
        candidates = await _access_route_candidates(org_id=org_id, assignments=scoped, db=db)
        if effective is None:
            effective = candidates
            continue
        # This scope has assignments, so it narrows the inherited set — even to empty
        # when none of its routes are currently routable. Skipping narrowing here would
        # let a key whose own policy has no active routes fall back to the broader
        # org/team set (privilege widening); fail closed instead.
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
) -> list[EffectiveAccessRouteCandidate]:
    candidates: list[EffectiveAccessRouteCandidate] = []
    for assignment in assignments:
        policy = await policy_kernel_repository.get_policy(
            policy_id=assignment.policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is None or policy.kind != "access" or not policy.is_active:
            continue
        revision = await policy_kernel_repository.get_active_policy_revision(
            org_id=org_id,
            policy_id=policy.id,
            db=db,
        )
        if revision is None:
            continue
        public_models = await policies_repository.list_access_policy_revision_public_models(
            org_id=org_id,
            policy_revision_id=revision.id,
            db=db,
        )
        for public_model in public_models:
            if not public_model.is_active:
                continue
            route_candidates = await policies_repository.list_access_policy_route_candidates(
                org_id=org_id,
                public_model_id=public_model.id,
                db=db,
            )
            candidates.extend(
                (public_model, candidate, assignment)
                for candidate in route_candidates
                if candidate.is_active
            )
    return candidates


def _route_candidate_matches(
    child: EffectiveAccessRouteCandidate,
    ancestor: EffectiveAccessRouteCandidate,
) -> bool:
    child_public_model, child_candidate, _child_assignment = child
    ancestor_public_model, ancestor_candidate, _ancestor_assignment = ancestor
    return (
        child_public_model.public_model_name == ancestor_public_model.public_model_name
        and child_candidate.provider_id == ancestor_candidate.provider_id
        and child_candidate.credential_pool_id == ancestor_candidate.credential_pool_id
        and (child_candidate.provider_model_offering_id or child_candidate.model_offering_id)
        == (ancestor_candidate.provider_model_offering_id or ancestor_candidate.model_offering_id)
    )


def _accessible_model_id(
    *,
    public_model: AccessPolicyPublicModel,
    candidate: AccessPolicyRouteCandidate,
    model: ModelOffering,
) -> str:
    return public_model.public_model_name


def _accessible_model_candidate(
    *,
    candidate: AccessPolicyRouteCandidate,
    model: ModelOffering,
    pool: CredentialPool,
    provider: Provider | None,
) -> AccessibleModelCandidate:
    return AccessibleModelCandidate(
        provider_id=model.provider_id,
        provider_name=provider.name if provider else "Unknown provider",
        pool_id=pool.id,
        pool_name=pool.name,
        model_offering_id=model.id,
        provider_model=model.provider_model_name,
        route_candidate_id=candidate.id,
        access_policy_route_id=None,
        priority=candidate.priority,
        weight=candidate.weight,
    )


def _to_resolved_route_attempt(
    *,
    virtual_key: VirtualKey,
    project: Project,
    requested_model: str,
    public_model: AccessPolicyPublicModel,
    candidate: AccessPolicyRouteCandidate,
    assignment: PolicyAssignment,
    model: ModelOffering,
    pool: CredentialPool,
    attempt_index: int,
    primary_route_candidate_id: UUID,
    limit_rules: list[tuple[LimitPolicyRule, LimitPolicy, UUID]],
) -> ResolvedRouteAttempt:
    return ResolvedRouteAttempt(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        access_policy_id=assignment.policy_id,
        access_policy_revision_id=public_model.policy_revision_id,
        access_policy_assignment_id=assignment.id,
        access_policy_route_id=None,
        public_model_id=public_model.id,
        route_candidate_id=candidate.id,
        public_model_name=public_model.public_model_name,
        routing_mode=public_model.routing_mode,
        model_offering_id=model.id,
        virtual_key_id=virtual_key.id,
        provider_id=candidate.provider_id,
        pool_id=pool.id,
        provider_key_id=None,
        requested_model=requested_model,
        provider_model=model.provider_model_name,
        routing_attempt_index=attempt_index,
        primary_route_candidate_id=primary_route_candidate_id,
        input_price_per_million_tokens=model.effective_input_price_per_million_tokens,
        output_price_per_million_tokens=model.effective_output_price_per_million_tokens,
        limit_policy_ids=list({policy.id for _rule, policy, _assignment_id in limit_rules}),
        limit_policies=[
            _to_resolved_limit_policy(rule, policy, assignment_id)
            for rule, policy, assignment_id in limit_rules
        ],
    )


async def _effective_limit_policies(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[tuple[LimitPolicy, UUID]]:
    assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    policies: list[tuple[LimitPolicy, UUID]] = []
    for assignment in assignments:
        policy = await policies_repository.get_limit_policy_by_shared_policy(
            shared_policy_id=assignment.policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is not None and policy.is_active:
            policies.append((policy, assignment.id))
    return policies


async def _effective_access_policy_references(
    *, org_id: UUID, assignments: list[PolicyAssignment], db: AsyncSession
) -> list[EffectivePolicyReference]:
    scope_order = {"org": 0, "team": 1, "project": 2, "virtual_key": 3}
    references: dict[UUID, EffectivePolicyReference] = {}
    for assignment in sorted(
        assignments, key=lambda item: scope_order.get(item.scope_type, -1), reverse=True
    ):
        if assignment.policy_id is not None:
            policy = await policy_kernel_repository.get_policy(
                policy_id=assignment.policy_id, org_id=org_id, db=db
            )
            if policy is not None and policy.kind == "access" and policy.is_active:
                references.setdefault(
                    policy.id,
                    EffectivePolicyReference(
                        id=policy.id, name=policy.name, source_scope=assignment.scope_type
                    ),
                )
            continue
    return list(references.values())


async def _access_policy_names(
    *, org_id: UUID, policy_ids: list[UUID], db: AsyncSession
) -> dict[UUID, str]:
    names: dict[UUID, str] = {}
    for policy_id in policy_ids:
        policy = await policies_repository.get_access_policy(
            policy_id=policy_id,
            org_id=org_id,
            db=db,
        )
        if policy is not None:
            names[policy.id] = policy.name
            continue
        shared_policy = await policy_kernel_repository.get_policy(
            policy_id=policy_id,
            org_id=org_id,
            db=db,
        )
        if shared_policy is not None:
            names[shared_policy.id] = shared_policy.name
    return names


async def _effective_limit_policy_references(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[EffectiveLimitReference]:
    assignments = await policy_kernel_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    references: list[EffectiveLimitReference] = []
    for assignment in assignments:
        policy = await policies_repository.get_limit_policy_by_shared_policy(
            shared_policy_id=assignment.policy_id, org_id=org_id, db=db
        )
        if policy is not None and policy.is_active:
            references.append(
                EffectiveLimitReference(
                    id=policy.id, name=policy.name, source_scope=assignment.scope_type
                )
            )
    return references


async def _matching_limit_policies(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    public_model: AccessPolicyPublicModel,
    candidate: AccessPolicyRouteCandidate,
    db: AsyncSession,
) -> list[tuple[LimitPolicyRule, LimitPolicy, UUID]]:
    policies = await _effective_limit_policies(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    rules: list[tuple[LimitPolicyRule, LimitPolicy, UUID]] = []
    for policy, assignment_id in policies:
        active_revision = await policy_kernel_repository.get_active_policy_revision(
            org_id=org_id,
            policy_id=policy.policy_id,
            db=db,
        )
        if active_revision is None:
            continue
        policy_rules = await policies_repository.list_limit_policy_revision_rules(
            org_id=org_id,
            limit_policy_id=policy.id,
            policy_revision_id=active_revision.id,
            db=db,
        )
        rules.extend(
            (rule, policy, assignment_id)
            for rule in policy_rules
            if rule.is_active
            and _limit_rule_matches_candidate(
                rule=rule,
                public_model=public_model,
                candidate=candidate,
            )
        )
    return rules


def _limit_rule_matches_candidate(
    *,
    rule: LimitPolicyRule,
    public_model: AccessPolicyPublicModel,
    candidate: AccessPolicyRouteCandidate,
) -> bool:
    return (
        (rule.provider_id is None or rule.provider_id == candidate.provider_id)
        and (
            rule.credential_pool_id is None
            or rule.credential_pool_id == candidate.credential_pool_id
        )
        and (
            rule.model_offering_id is None or rule.model_offering_id == candidate.model_offering_id
        )
        and (
            rule.access_policy_id is None or rule.access_policy_id == public_model.access_policy_id
        )
    )


async def _get_project_or_raise(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None:
        raise ProjectNotFoundError
    return project


async def _ensure_project_slug_available(
    *, org_id: UUID, team_id: UUID, slug: str, db: AsyncSession
) -> None:
    existing = await repository.get_project_by_slug(
        org_id=org_id,
        team_id=team_id,
        slug=slug,
        db=db,
    )
    if existing is not None:
        raise ProjectSlugAlreadyExistsError


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


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


async def _to_project_response(project: Project, *, db: AsyncSession) -> ProjectResponse:
    team = await db.get(Team, project.team_id)
    return ProjectResponse.model_validate(project).model_copy(
        update={"team_name": team.name if team else None}
    )


def _to_resolved_limit_policy(
    rule: LimitPolicyRule, policy: LimitPolicy, assignment_id: UUID
) -> ResolvedLimitPolicy:
    return ResolvedLimitPolicy(
        limit_policy_assignment_id=assignment_id,
        limit_policy_id=policy.id,
        limit_policy_revision_id=rule.policy_revision_id,
        limit_policy_name=policy.name,
        limit_policy_rule_id=rule.id,
        name=rule.name,
        limit_type=rule.limit_type,
        limit_value=rule.limit_value,
        interval_unit=rule.interval_unit,
        interval_count=rule.interval_count,
    )


async def _to_virtual_key_response(
    virtual_key: VirtualKey,
    *,
    project: Project,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    derived = await _derive_virtual_key_state(
        virtual_key=virtual_key, project=project, scope=scope, db=db
    )
    creator = await db.get(User, virtual_key.created_by) if virtual_key.created_by else None
    revoker = await db.get(User, virtual_key.revoked_by) if virtual_key.revoked_by else None
    return VirtualKeyResponse(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        supersedes_key_id=virtual_key.supersedes_key_id,
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        status=derived[0],
        is_usable=derived[1],
        created_by=virtual_key.created_by,
        creator_name=creator.name if creator else None,
        creator_email=creator.email if creator else None,
        last_used_at=virtual_key.last_used_at,
        expires_at=virtual_key.expires_at,
        deprecated_at=virtual_key.deprecated_at,
        revoked_at=virtual_key.revoked_at,
        revoked_by=virtual_key.revoked_by,
        revoker_name=revoker.name if revoker else None,
        revoker_email=revoker.email if revoker else None,
        revoked_reason=virtual_key.revoked_reason,
        created_at=virtual_key.created_at,
        updated_at=virtual_key.updated_at,
    )


def _key_prefix(raw_key: str) -> str:
    return raw_key[:16]


def _to_inventory_item(
    *,
    virtual_key: VirtualKey,
    project: Project,
    team: Team,
    creator: User | None,
    can_manage: bool,
    routing_ready: bool,
) -> VirtualKeyInventoryItem:
    status, is_usable = _derive_inventory_state(
        virtual_key=virtual_key,
        project=project,
        team=team,
        routing_ready=routing_ready,
    )
    return VirtualKeyInventoryItem(
        id=virtual_key.id,
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        project_id=project.id,
        supersedes_key_id=virtual_key.supersedes_key_id,
        project_name=project.name,
        project_is_active=project.is_active,
        team_id=team.id,
        team_name=team.name,
        team_is_active=team.is_active,
        status=status,
        is_usable=is_usable,
        can_manage=can_manage,
        created_by=virtual_key.created_by,
        creator_name=creator.name if creator else None,
        creator_email=creator.email if creator else None,
        created_at=virtual_key.created_at,
        expires_at=virtual_key.expires_at,
        deprecated_at=virtual_key.deprecated_at,
        last_used_at=virtual_key.last_used_at,
        revoked_at=virtual_key.revoked_at,
        revoked_by=virtual_key.revoked_by,
        revoked_reason=virtual_key.revoked_reason,
    )


def _derive_inventory_state(
    *,
    virtual_key: VirtualKey,
    project: Project,
    team: Team,
    routing_ready: bool,
) -> tuple[str, bool]:
    if virtual_key.revoked_at is not None:
        return "revoked", False
    now = datetime.now(UTC)
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= now:
        return "expired", False
    if not project.is_active:
        return "project_archived", False
    if not team.is_active:
        return "team_archived", False
    if not routing_ready:
        return "no_effective_access", False
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= now + timedelta(
        days=EXPIRING_SOON_DAYS
    ):
        return "expiring_soon", True
    if virtual_key.last_used_at is None:
        return "unused", True
    return "active", True


async def _derive_virtual_key_state(
    *,
    virtual_key: VirtualKey,
    project: Project,
    scope: Scope,
    db: AsyncSession,
    team: Team | None = None,
) -> tuple[str, bool]:
    if virtual_key.revoked_at is not None:
        return "revoked", False
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(UTC):
        return "expired", False
    if not project.is_active:
        return "project_archived", False
    if team is None:
        try:
            team_response = await teams_facade.get_team(team_id=project.team_id, scope=scope, db=db)
            team_active = team_response.is_active
        except TeamNotFoundError:
            team_active = False
    else:
        team_active = team.is_active
    if not team_active:
        return "team_archived", False

    summary = await _build_effective_access_summary(project=project, virtual_key=virtual_key, db=db)
    if not summary.is_usable:
        return "no_effective_access", False
    if virtual_key.expires_at is not None and _as_utc(virtual_key.expires_at) <= datetime.now(
        UTC
    ) + timedelta(days=EXPIRING_SOON_DAYS):
        return "expiring_soon", True
    if virtual_key.last_used_at is None:
        return "unused", True
    return "active", True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
