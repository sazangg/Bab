from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth import read_models as auth_read_models
from app.modules.keys import facade as keys_facade
from app.modules.keys import read_models as keys_read_models
from app.modules.usage import read_models as usage_read_models
from app.modules.workspace import read_models as workspace_read_models
from app.modules.workspace.errors import ProjectNotFoundError, TeamNotFoundError
from app.modules.workspace.internal import repository
from app.modules.workspace.schemas import (
    ProjectArchiveImpactResponse,
    TeamArchiveImpactResponse,
)

IMPACT_USAGE_WINDOW_DAYS = 30


async def get_team_archive_impact(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> TeamArchiveImpactResponse:
    team = await repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
    if team is None:
        raise TeamNotFoundError
    since = datetime.now(UTC) - timedelta(days=IMPACT_USAGE_WINDOW_DAYS)
    usage_summary = await usage_read_models.get_recent_workspace_usage_summary(
        org_id=scope.org_id, since=since, team_id=team_id, db=db
    )
    team_admin_count, team_member_count = await auth_read_models.count_team_members_by_role(
        org_id=scope.org_id,
        team_id=team_id,
        db=db,
    )
    active_project_ids = await workspace_read_models.list_project_ids_for_team(
        org_id=scope.org_id,
        team_id=team_id,
        active_only=True,
        db=db,
    )
    return TeamArchiveImpactResponse(
        active_project_count=await repository.count_active_team_projects(
            org_id=scope.org_id,
            team_id=team_id,
            db=db,
        ),
        active_virtual_key_count=await keys_read_models.count_active_virtual_keys_for_project_ids(
            org_id=scope.org_id,
            project_ids=active_project_ids,
            db=db,
        ),
        team_admin_count=team_admin_count,
        team_member_count=team_member_count,
        recent_usage_window_days=IMPACT_USAGE_WINDOW_DAYS,
        recent_request_count=usage_summary.request_count,
        recent_cost_cents=usage_summary.cost_cents,
    )


async def get_project_archive_impact(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProjectArchiveImpactResponse:
    project_state = await workspace_read_models.get_project_runtime_state(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    if project_state is None:
        raise ProjectNotFoundError
    since = datetime.now(UTC) - timedelta(days=IMPACT_USAGE_WINDOW_DAYS)
    usage_summary = await usage_read_models.get_recent_workspace_usage_summary(
        org_id=scope.org_id, since=since, project_id=project_id, db=db
    )
    count_project_ids = {project_id} if project_state.is_active else set()
    return ProjectArchiveImpactResponse(
        active_virtual_key_count=await keys_read_models.count_active_virtual_keys_for_project_ids(
            org_id=scope.org_id,
            project_ids=count_project_ids,
            db=db,
        ),
        recent_usage_window_days=IMPACT_USAGE_WINDOW_DAYS,
        recent_request_count=usage_summary.request_count,
        recent_cost_cents=usage_summary.cost_cents,
        effective_access=await keys_facade.get_project_effective_access(
            project_id=project_id,
            scope=scope,
            db=db,
        ),
    )
