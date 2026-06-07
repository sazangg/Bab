import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
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
    VirtualKeyAlreadyRevokedError,
    VirtualKeyNotFoundError,
)
from app.modules.keys.internal import repository
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.keys.schemas import (
    AccessibleModel,
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
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedLimitPolicy,
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
    AccessPolicyRoute,
    LimitPolicy,
    LimitPolicyRule,
    PolicyAssignment,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderNotFoundError
from app.modules.settings import facade as settings_facade
from app.modules.teams import facade as teams_facade
from app.modules.teams.errors import TeamInactiveError, TeamNotFoundError

logger = structlog.get_logger(__name__)
EXPIRING_SOON_DAYS = 7
IMPACT_USAGE_WINDOW_DAYS = 30


type ResolvedKeyProject = tuple[VirtualKey, Project]
type EffectiveAccessRouteCandidate = tuple[AccessPolicyRoute, UUID, PolicyAssignment]
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
    scan_limit = max(limit, 100)
    scan_offset = 0
    total = 0
    page_items: list[VirtualKeyInventoryItem] = []
    while True:
        rows, _ = await repository.list_virtual_key_inventory(
            org_id=scope.org_id,
            team_ids=visible_team_ids,
            project_ids=visible_project_ids,
            team_id=team_id,
            project_id=project_id,
            status=status,
            search=search,
            usage=usage,
            limit=scan_limit,
            offset=scan_offset,
            db=db,
        )
        if not rows:
            break
        items = await _inventory_items_from_rows(
            rows=rows,
            manageable_team_ids=manageable_team_ids,
            manageable_project_ids=manageable_project_ids,
            can_manage_all=can_manage_all,
            db=db,
        )
        for item in items:
            if item.status != status:
                continue
            if total >= offset and len(page_items) < limit:
                page_items.append(item)
            total += 1
        if len(rows) < scan_limit:
            break
        scan_offset += scan_limit

    return VirtualKeyInventoryPage(
        items=page_items,
        total=total,
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
    return [
        await _to_inventory_item(
            virtual_key=virtual_key,
            project=project,
            team=team,
            creator=creator,
            can_manage=(
                can_manage_all
                or team.id in manageable_team_ids
                or project.id in manageable_project_ids
            ),
            db=db,
        )
        for virtual_key, project, team, creator in rows
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
                    "from": virtual_key.expires_at.isoformat()
                    if virtual_key.expires_at
                    else None,
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
    limit_rules = await _matching_limit_policies(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        route=route,
        model_offering_id=model_offering_id,
        db=db,
    )

    return ResolvedAccess(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=virtual_key.project_id,
        access_policy_id=route.access_policy_id,
        access_policy_route_id=route.id,
        model_offering_id=model_offering_id,
        limit_policy_ids=list({policy.id for _rule, policy, _assignment_id in limit_rules}),
        limit_policies=[
            _to_resolved_limit_policy(rule, policy, assignment_id)
            for rule, policy, assignment_id in limit_rules
        ],
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
    for route, model_offering_id, _assignment in await _effective_access_routes(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        db=db,
    ):
        routable = await _routable_route_model(
            org_id=virtual_key.org_id,
            route=route,
            model_offering_id=model_offering_id,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        if model.provider_model_name in seen:
            continue
        seen.add(model.provider_model_name)
        models.append(
            AccessibleModel(
                id=model.provider_model_name,
                owned_by=model.provider_id.hex,
                provider_id=model.provider_id,
                model_offering_id=model.id,
                access_policy_id=route.access_policy_id,
                access_policy_route_id=route.id,
                pool_id=pool.id,
                alias=model.alias,
            )
        )
    return models


async def list_project_accessible_models(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[AccessibleModel]:
    project = await repository.get_project(project_id=project_id, org_id=scope.org_id, db=db)
    if project is None or not project.is_active:
        raise ProjectNotFoundError
    models: list[AccessibleModel] = []
    seen: set[tuple[UUID, UUID]] = set()
    for route, model_offering_id, _assignment in await _effective_access_routes(
        org_id=scope.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=None,
        db=db,
    ):
        routable = await _routable_route_model(
            org_id=scope.org_id,
            route=route,
            model_offering_id=model_offering_id,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        dedupe_key = (model.provider_id, model.id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        models.append(
            AccessibleModel(
                id=model.provider_model_name,
                owned_by=model.provider_id.hex,
                provider_id=model.provider_id,
                model_offering_id=model.id,
                access_policy_id=route.access_policy_id,
                access_policy_route_id=route.id,
                pool_id=pool.id,
                alias=model.alias,
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
    return await _build_effective_access_summary(
        project=project, virtual_key=virtual_key, db=db
    )


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

    routes = await _effective_access_routes(
        org_id=project.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id if virtual_key else None,
        db=db,
    )
    routable_routes: list[EffectiveRouteSummary] = []
    policy_names = await _access_policy_names(
        org_id=project.org_id,
        policy_ids=list({route.access_policy_id for route, _model_id, _assignment in routes}),
        db=db,
    )
    for route, model_offering_id, assignment in routes:
        routable = await _routable_route_model(
            org_id=project.org_id,
            route=route,
            model_offering_id=model_offering_id,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
        routable_routes.append(
            EffectiveRouteSummary(
                provider_id=route.provider_id,
                credential_pool_id=route.credential_pool_id,
                model_offering_id=model.id,
                provider_model=model.provider_model_name,
                alias=model.alias,
                access_policy_id=route.access_policy_id,
                access_policy_name=policy_names.get(route.access_policy_id),
                access_policy_assignment_id=assignment.id,
                source_scope=assignment.scope_type,
            )
        )

    route_assignments = list(
        {assignment.id: assignment for _route, _model_id, assignment in routes}.values()
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


async def _routable_route_model(
    *,
    org_id: UUID,
    route: AccessPolicyRoute,
    model_offering_id: UUID,
    db: AsyncSession,
):
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
        credentials = await providers_facade.list_credential_pool_credentials(
            provider_id=route.provider_id,
            pool_id=route.credential_pool_id,
            scope=Scope(org_id=org_id),
            db=db,
        )
    except ProviderNotFoundError:
        return None
    if (
        not pool.is_active
        or not model.is_active
        or pool.provider_id != route.provider_id
        or model.provider_id != route.provider_id
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
    for route, model_offering_id, _assignment in candidates:
        routable = await _routable_route_model(
            org_id=org_id,
            route=route,
            model_offering_id=model_offering_id,
            db=db,
        )
        if routable is None:
            continue
        pool, model = routable
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
) -> list[EffectiveAccessRouteCandidate]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
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
) -> list[EffectiveAccessRouteCandidate]:
    candidates: list[EffectiveAccessRouteCandidate] = []
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
            candidates.extend(
                (route, UUID(str(model_id)), assignment)
                for model_id in route.model_offering_ids
            )
    return candidates


def _route_candidate_matches(
    child: EffectiveAccessRouteCandidate,
    ancestor: EffectiveAccessRouteCandidate,
) -> bool:
    child_route, child_model_id, _child_assignment = child
    ancestor_route, ancestor_model_id, _ancestor_assignment = ancestor
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
) -> list[tuple[LimitPolicy, UUID]]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    policies: list[tuple[LimitPolicy, UUID]] = []
    for assignment in assignments:
        if assignment.limit_policy_id is None:
            continue
        policy = await policies_repository.get_limit_policy(
            policy_id=assignment.limit_policy_id,
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
        if assignment.access_policy_id is None:
            continue
        policy = await policies_repository.get_access_policy(
            policy_id=assignment.access_policy_id, org_id=org_id, db=db
        )
        if policy is not None and policy.is_active:
            references.setdefault(
                policy.id,
                EffectivePolicyReference(
                    id=policy.id, name=policy.name, source_scope=assignment.scope_type
                ),
            )
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
    return names


async def _effective_limit_policy_references(
    *,
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> list[EffectiveLimitReference]:
    assignments = await policies_repository.list_active_policy_assignments_for_targets(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        policy_type="limit",
        db=db,
    )
    references: list[EffectiveLimitReference] = []
    for assignment in assignments:
        if assignment.limit_policy_id is None:
            continue
        policy = await policies_repository.get_limit_policy(
            policy_id=assignment.limit_policy_id, org_id=org_id, db=db
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
    route: AccessPolicyRoute,
    model_offering_id: UUID,
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
        policy_rules = await policies_repository.list_limit_policy_rules(
            org_id=org_id,
            limit_policy_id=policy.id,
            db=db,
        )
        rules.extend(
            (rule, policy, assignment_id)
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


def _to_project_response(project: Project) -> ProjectResponse:
    return ProjectResponse.model_validate(project)


def _to_resolved_limit_policy(
    rule: LimitPolicyRule, policy: LimitPolicy, assignment_id: UUID
) -> ResolvedLimitPolicy:
    return ResolvedLimitPolicy(
        limit_policy_assignment_id=assignment_id,
        limit_policy_id=policy.id,
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
    return VirtualKeyResponse(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        status=derived[0],
        is_usable=derived[1],
        created_by=virtual_key.created_by,
        last_used_at=virtual_key.last_used_at,
        expires_at=virtual_key.expires_at,
        revoked_at=virtual_key.revoked_at,
        revoked_by=virtual_key.revoked_by,
        revoked_reason=virtual_key.revoked_reason,
        created_at=virtual_key.created_at,
        updated_at=virtual_key.updated_at,
    )


def _key_prefix(raw_key: str) -> str:
    return raw_key[:16]


async def _to_inventory_item(
    *,
    virtual_key: VirtualKey,
    project: Project,
    team: Team,
    creator: User | None,
    can_manage: bool,
    db: AsyncSession,
) -> VirtualKeyInventoryItem:
    status, is_usable = await _derive_virtual_key_state(
        virtual_key=virtual_key,
        project=project,
        scope=Scope(org_id=virtual_key.org_id),
        db=db,
        team=team,
    )
    return VirtualKeyInventoryItem(
        id=virtual_key.id,
        name=virtual_key.name,
        key_prefix=virtual_key.key_prefix,
        project_id=project.id,
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
        last_used_at=virtual_key.last_used_at,
        revoked_at=virtual_key.revoked_at,
        revoked_by=virtual_key.revoked_by,
        revoked_reason=virtual_key.revoked_reason,
    )


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
            team_response = await teams_facade.get_team(
                team_id=project.team_id, scope=scope, db=db
            )
            team_active = team_response.is_active
        except TeamNotFoundError:
            team_active = False
    else:
        team_active = team.is_active
    if not team_active:
        return "team_archived", False

    summary = await _build_effective_access_summary(
        project=project, virtual_key=virtual_key, db=db
    )
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
