from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import generate_virtual_key, hash_token
from app.modules.activity import facade as activity_facade
from app.modules.auth import read_models as auth_read_models
from app.modules.auth.schemas import AuthenticatedUser, UserLabel
from app.modules.keys.errors import (
    PolicyNotConfiguredError,
    ProjectAccessUnavailableError,
    SecretDeliveryDisabledError,
    VirtualKeyAlreadyRevokedError,
    VirtualKeyNotFoundError,
    VirtualKeyOverlapActiveError,
)
from app.modules.keys.internal import access_planning, repository
from app.modules.keys.internal.models import VirtualKey
from app.modules.keys.schemas import (
    CreatedVirtualKeyResponse,
    CreateVirtualKeyRequest,
    RotateVirtualKeyRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyIdentity,
    VirtualKeyInventoryItem,
    VirtualKeyInventoryPage,
    VirtualKeyOption,
    VirtualKeyResponse,
    VirtualKeyRevokeImpactResponse,
    VirtualKeyTarget,
)
from app.modules.settings import facade as settings_facade
from app.modules.usage import read_models as usage_read_models
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace import read_models as workspace_read_models
from app.modules.workspace.errors import ProjectInactiveError, ProjectNotFoundError
from app.modules.workspace.schemas import TeamReadState

logger = structlog.get_logger(__name__)
EXPIRING_SOON_DAYS = 7
IMPACT_USAGE_WINDOW_DAYS = 30


class ProjectRuntimeLike(Protocol):
    id: UUID
    org_id: UUID
    team_id: UUID
    name: str
    is_active: bool


type ProjectRuntimeState = workspace_read_models.WorkspaceProjectRuntimeState


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
        await workspace_facade.ensure_team_active(team_id=project.team_id, scope=scope, db=db)
        access_summary = await access_planning.build_effective_access_summary(
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

    inventory_project_ids = await _inventory_project_ids(
        scope=scope,
        visible_team_ids=visible_team_ids,
        visible_project_ids=visible_project_ids,
        team_id=team_id,
        project_id=project_id,
        status=status,
        db=db,
    )
    virtual_keys, total = await repository.list_virtual_key_inventory(
        org_id=scope.org_id,
        project_ids=inventory_project_ids,
        status=status,
        search=search,
        usage=usage,
        limit=limit,
        offset=offset,
        db=db,
    )
    rows = await _inventory_rows_from_keys(
        org_id=scope.org_id,
        virtual_keys=virtual_keys,
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
    inventory_project_ids = await _inventory_project_ids(
        scope=scope,
        visible_team_ids=visible_team_ids,
        visible_project_ids=visible_project_ids,
        team_id=team_id,
        project_id=project_id,
        status=None,
        db=db,
    )
    virtual_keys, _ = await repository.list_virtual_key_inventory(
        org_id=scope.org_id,
        project_ids=inventory_project_ids,
        status=None,
        search=search,
        usage=usage,
        limit=None,
        offset=0,
        include_total=False,
        db=db,
    )
    rows = await _inventory_rows_from_keys(
        org_id=scope.org_id,
        virtual_keys=virtual_keys,
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


async def _inventory_project_ids(
    *,
    scope: Scope,
    visible_team_ids: set[UUID] | None,
    visible_project_ids: set[UUID] | None,
    team_id: UUID | None,
    project_id: UUID | None,
    status: str | None,
    db: AsyncSession,
) -> set[UUID]:
    project_active: bool | None = None
    team_active: bool | None = None
    if status == "project_archived":
        project_active = False
    elif status == "team_archived":
        project_active = True
        team_active = False
    elif status in {"active", "expiring_soon", "unused", "no_effective_access"}:
        project_active = True
        team_active = True
    return await workspace_read_models.list_project_ids_for_hierarchy_filter(
        org_id=scope.org_id,
        visible_team_ids=visible_team_ids,
        visible_project_ids=visible_project_ids,
        team_id=team_id,
        project_id=project_id,
        project_active=project_active,
        team_active=team_active,
        db=db,
    )


async def _inventory_rows_from_keys(
    *,
    org_id: UUID,
    virtual_keys: list[VirtualKey],
    db: AsyncSession,
) -> list[tuple[VirtualKey, ProjectRuntimeState]]:
    if not virtual_keys:
        return []
    project_states = await workspace_read_models.get_project_runtime_states(
        org_id=org_id,
        project_ids={virtual_key.project_id for virtual_key in virtual_keys},
        db=db,
    )
    return [
        (virtual_key, project_states[virtual_key.project_id])
        for virtual_key in virtual_keys
        if virtual_key.project_id in project_states
    ]


async def _inventory_items_from_rows(
    *,
    rows: list[tuple[VirtualKey, ProjectRuntimeLike]],
    manageable_team_ids: set[UUID],
    manageable_project_ids: set[UUID],
    can_manage_all: bool,
    db: AsyncSession,
) -> list[VirtualKeyInventoryItem]:
    routing_ready = await access_planning.batch_inventory_routing_readiness(rows=rows, db=db)
    if not rows:
        return []
    org_id = rows[0][0].org_id
    scope = Scope(org_id=org_id)
    team_states = await workspace_facade.get_team_read_states(
        team_ids={project.team_id for _key, project in rows},
        scope=scope,
        db=db,
    )
    user_ids = {key.created_by for key, _project in rows if key.created_by is not None}
    user_labels = await auth_read_models.get_user_labels(
        org_id=org_id,
        user_ids=user_ids,
        db=db,
    )
    return [
        _to_inventory_item(
            virtual_key=virtual_key,
            project=project,
            team_state=team_states.get(project.team_id),
            creator_label=user_labels.get(virtual_key.created_by),
            can_manage=(
                can_manage_all
                or project.team_id in manageable_team_ids
                or project.id in manageable_project_ids
            ),
            routing_ready=routing_ready.get(virtual_key.id, False),
        )
        for virtual_key, project in rows
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


async def get_virtual_key_identity(
    *, key_id: UUID, scope: Scope, db: AsyncSession
) -> VirtualKeyIdentity | None:
    virtual_key = await repository.get_virtual_key_by_id(
        org_id=scope.org_id,
        key_id=key_id,
        db=db,
    )
    if virtual_key is None:
        return None
    return VirtualKeyIdentity(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
    )


async def get_virtual_key_labels(
    *, virtual_key_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await repository.get_virtual_key_labels(
        org_id=scope.org_id,
        virtual_key_ids=virtual_key_ids,
        db=db,
    )


async def list_virtual_key_ids_for_project_ids(
    *, project_ids: set[UUID], scope: Scope, db: AsyncSession
) -> set[UUID]:
    return await repository.list_virtual_key_ids_for_project_ids(
        org_id=scope.org_id,
        project_ids=project_ids,
        db=db,
    )


async def list_virtual_key_options_for_project_ids(
    *, project_ids: set[UUID], usable_only: bool, scope: Scope, db: AsyncSession
) -> list[VirtualKeyOption]:
    project_states = await workspace_read_models.get_project_runtime_states(
        org_id=scope.org_id,
        project_ids=project_ids,
        db=db,
    )
    rows = await repository.list_virtual_key_options_for_project_ids(
        org_id=scope.org_id,
        project_ids=set(project_states),
        usable_only=usable_only,
        db=db,
    )
    options = [
        VirtualKeyOption(
            id=key_id,
            name=key_name,
            project_id=project_id,
            project_name=project_states[project_id].name,
        )
        for key_id, key_name, project_id in rows
        if project_id in project_states
    ]
    return sorted(options, key=lambda item: (item.project_name, item.name))


async def list_virtual_key_options_by_ids(
    *, virtual_key_ids: set[UUID], usable_only: bool, scope: Scope, db: AsyncSession
) -> list[VirtualKeyOption]:
    rows = await repository.list_virtual_key_options_by_ids(
        org_id=scope.org_id,
        virtual_key_ids=virtual_key_ids,
        usable_only=usable_only,
        db=db,
    )
    project_states = await workspace_read_models.get_project_runtime_states(
        org_id=scope.org_id,
        project_ids={project_id for _key_id, _key_name, project_id in rows},
        db=db,
    )
    options = [
        VirtualKeyOption(
            id=key_id,
            name=key_name,
            project_id=project_id,
            project_name=project_states[project_id].name,
        )
        for key_id, key_name, project_id in rows
        if project_id in project_states
    ]
    return sorted(options, key=lambda item: (item.project_name, item.name))


async def get_usable_virtual_key_target(
    *, virtual_key_id: UUID, scope: Scope, db: AsyncSession
) -> VirtualKeyTarget | None:
    virtual_key = await repository.get_usable_virtual_key_target(
        org_id=scope.org_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )
    if virtual_key is None:
        return None
    project = await workspace_read_models.get_project_runtime_state(
        org_id=scope.org_id,
        project_id=virtual_key.project_id,
        db=db,
    )
    if project is None or not project.is_active:
        return None
    return VirtualKeyTarget(
        org_id=virtual_key.org_id,
        team_id=project.team_id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        virtual_key_name=virtual_key.name,
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
        await workspace_facade.ensure_team_active(team_id=project.team_id, scope=scope, db=db)
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
    usage_summary = await usage_read_models.get_recent_workspace_usage_summary(
        org_id=scope.org_id, since=since, virtual_key_id=key_id, db=db
    )
    request_count = usage_summary.request_count
    cost_cents = usage_summary.cost_cents
    effective_access = await access_planning.build_effective_access_summary(
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


async def _get_active_project(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectRuntimeState:
    await workspace_read_models.ensure_organization_active(org_id=scope.org_id, db=db)
    project = await _get_project_or_raise(project_id=project_id, scope=scope, db=db)
    if not project.is_active:
        raise ProjectInactiveError
    return project


async def _get_project_or_raise(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectRuntimeState:
    project = await workspace_read_models.get_project_runtime_state(
        project_id=project_id, org_id=scope.org_id, db=db
    )
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


async def _to_virtual_key_response(
    virtual_key: VirtualKey,
    *,
    project: ProjectRuntimeState,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    derived = await _derive_virtual_key_state(
        virtual_key=virtual_key, project=project, scope=scope, db=db
    )
    user_ids = {
        user_id
        for user_id in (virtual_key.created_by, virtual_key.revoked_by)
        if user_id is not None
    }
    user_labels = await auth_read_models.get_user_labels(
        org_id=virtual_key.org_id,
        user_ids=user_ids,
        db=db,
    )
    creator = user_labels.get(virtual_key.created_by)
    revoker = user_labels.get(virtual_key.revoked_by)
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
        creator_name=creator.display_name if creator else None,
        creator_email=creator.email if creator else None,
        last_used_at=virtual_key.last_used_at,
        expires_at=virtual_key.expires_at,
        deprecated_at=virtual_key.deprecated_at,
        revoked_at=virtual_key.revoked_at,
        revoked_by=virtual_key.revoked_by,
        revoker_name=revoker.display_name if revoker else None,
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
    project: ProjectRuntimeLike,
    team_state: TeamReadState | None,
    creator_label: UserLabel | None,
    can_manage: bool,
    routing_ready: bool,
) -> VirtualKeyInventoryItem:
    status, is_usable = _derive_inventory_state(
        virtual_key=virtual_key,
        project=project,
        team_is_active=team_state.is_active if team_state else False,
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
        team_id=project.team_id,
        team_name=team_state.name if team_state else "",
        team_is_active=team_state.is_active if team_state else False,
        status=status,
        is_usable=is_usable,
        can_manage=can_manage,
        created_by=virtual_key.created_by,
        creator_name=creator_label.display_name if creator_label else None,
        creator_email=creator_label.email if creator_label else None,
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
    project: ProjectRuntimeLike,
    team_is_active: bool,
    routing_ready: bool,
) -> tuple[str, bool]:
    if virtual_key.revoked_at is not None:
        return "revoked", False
    now = datetime.now(UTC)
    if (
        virtual_key.expires_at is not None
        and _as_utc(virtual_key.expires_at) <= now
    ):
        return "expired", False
    if not project.is_active:
        return "project_archived", False
    if not team_is_active:
        return "team_archived", False
    if not routing_ready:
        return "no_effective_access", False
    if (
        virtual_key.expires_at is not None
        and _as_utc(virtual_key.expires_at)
        <= now + timedelta(days=EXPIRING_SOON_DAYS)
    ):
        return "expiring_soon", True
    if virtual_key.last_used_at is None:
        return "unused", True
    return "active", True


async def _derive_virtual_key_state(
    *,
    virtual_key: VirtualKey,
    project: ProjectRuntimeState,
    scope: Scope,
    db: AsyncSession,
    team_is_active: bool | None = None,
) -> tuple[str, bool]:
    if virtual_key.revoked_at is not None:
        return "revoked", False
    if (
        virtual_key.expires_at is not None
        and _as_utc(virtual_key.expires_at) <= datetime.now(UTC)
    ):
        return "expired", False
    if not project.is_active:
        return "project_archived", False
    if team_is_active is None:
        team_identity = await workspace_facade.get_team_identity(
            team_id=project.team_id,
            scope=scope,
            db=db,
        )
        team_is_active = team_identity.is_active if team_identity else False
    if not team_is_active:
        return "team_archived", False

    summary = await access_planning.build_effective_access_summary(
        project=project, virtual_key=virtual_key, db=db
    )
    if not summary.is_usable:
        return "no_effective_access", False
    if (
        virtual_key.expires_at is not None
        and _as_utc(virtual_key.expires_at)
        <= datetime.now(UTC) + timedelta(days=EXPIRING_SOON_DAYS)
    ):
        return "expiring_soon", True
    if virtual_key.last_used_at is None:
        return "unused", True
    return "active", True

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
