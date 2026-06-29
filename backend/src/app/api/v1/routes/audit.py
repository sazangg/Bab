import csv
import json
from datetime import datetime
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response as FastApiResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_scope, require_permission
from app.core.csv_safe import sanitize_csv_cell
from app.core.database import Scope, get_db
from app.modules.audit import facade
from app.modules.audit.schemas import AuditEventPageResponse, AuditVerificationResponse
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization.permissions import Permissions

router = APIRouter(prefix="/audit", tags=["audit"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
AuditViewer = Annotated[AuthenticatedUser, Depends(require_permission(Permissions.AUDIT_VIEW))]


@router.get("")
async def list_audit_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> AuditEventPageResponse:
    events = await facade.list_audit_events(
        scope=scope,
        db=db,
        limit=limit + 1,
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        search=q.strip() if q and q.strip() else None,
        before_at=before_at,
        before_id=before_id,
    )
    items = events[:limit]
    has_more = len(events) > limit
    next_item = items[-1] if has_more and items else None
    return AuditEventPageResponse(
        items=items,
        limit=limit,
        has_more=has_more,
        next_before_at=next_item.created_at if next_item else None,
        next_before_id=next_item.id if next_item else None,
    )


@router.get("/export")
async def export_audit_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> FastApiResponse:
    events = await facade.list_audit_events(
        scope=scope,
        db=db,
        limit=None,
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        search=q.strip() if q and q.strip() else None,
    )
    return _csv_response(
        filename="bab-audit-events.csv",
        header=[
            "id",
            "created_at",
            "org_id",
            "actor_user_id",
            "actor_email",
            "actor_role",
            "action",
            "entity_type",
            "entity_id",
            "metadata",
            "previous_hash",
            "event_hash",
            "signature_algorithm",
        ],
        rows=[
            [
                event.id,
                event.created_at,
                event.org_id,
                event.actor_user_id,
                event.actor_email,
                event.actor_role,
                event.action,
                event.entity_type,
                event.entity_id,
                json.dumps(event.metadata, sort_keys=True),
                event.previous_hash,
                event.event_hash,
                event.signature_algorithm,
            ]
            for event in events
        ],
    )


@router.get("/verify")
async def verify_audit_chain(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
) -> AuditVerificationResponse:
    return await facade.verify_audit_chain(scope=scope, db=db)


def _csv_response(*, filename: str, header: list[str], rows: list[list[object]]) -> FastApiResponse:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows([sanitize_csv_cell(cell) for cell in row] for row in rows)
    return FastApiResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
