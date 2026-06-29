from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
    require_permission,
    require_permission_or_scoped_admin,
)
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.errors import AuthorizationDeniedError
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import AuthorizationTarget
from app.modules.guardrails import facade
from app.modules.guardrails.errors import (
    GuardrailAssignmentConflictError,
    GuardrailAssignmentNotFoundError,
    GuardrailAssignmentTargetNotFoundError,
    GuardrailPolicyNotFoundError,
)
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    GuardrailAssignmentResponse,
    GuardrailEventResponse,
    GuardrailImpactResponse,
    GuardrailPolicyOptionResponse,
    GuardrailPolicyResponse,
    GuardrailSimulationRequest,
    GuardrailSimulationResponse,
    UpdateGuardrailAssignmentRequest,
    UpdateGuardrailPolicyRequest,
)

router = APIRouter(prefix="/guardrails", tags=["guardrails"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
GuardrailViewer = Annotated[
    AuthenticatedUser,
    Depends(require_permission_or_scoped_admin(Permissions.GUARDRAILS_VIEW)),
]
GuardrailAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_permission(Permissions.GUARDRAILS_MANAGE)),
]
AssignmentActor = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("/policies")
async def list_policies(
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
) -> list[GuardrailPolicyResponse]:
    return await facade.list_policies(scope=scope, db=db, actor=actor)


@router.get("/policy-options")
async def list_policy_options(
    scope: RequestScope,
    db: DatabaseSession,
    _: GuardrailViewer,
) -> list[GuardrailPolicyOptionResponse]:
    return await facade.list_policy_options(scope=scope, db=db)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: CreateGuardrailPolicyRequest,
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailPolicyResponse:
    return await facade.create_policy(payload=payload, actor=actor, scope=scope, db=db)


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: UUID,
    payload: UpdateGuardrailPolicyRequest,
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailPolicyResponse:
    try:
        return await facade.update_policy(
            policy_id=policy_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: UUID,
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_policy(policy_id=policy_id, actor=actor, scope=scope, db=db)
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc


@router.get("/policies/{policy_id}/impact")
async def get_policy_impact(
    policy_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
) -> GuardrailImpactResponse:
    try:
        return await facade.get_policy_impact(
            policy_id=policy_id,
            scope=scope,
            db=db,
            actor=actor,
        )
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc


@router.get("/assignments")
async def list_assignments(
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
) -> list[GuardrailAssignmentResponse]:
    return await facade.list_assignments(scope=scope, db=db, actor=actor)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: CreateGuardrailAssignmentRequest,
    actor: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailAssignmentResponse:
    try:
        await _require_assignment_admin(
            user=actor,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            scope=scope,
            db=db,
        )
        return await facade.create_assignment(payload=payload, actor=actor, scope=scope, db=db)
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc
    except GuardrailAssignmentTargetNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="guardrail assignment target not found",
        ) from exc
    except GuardrailAssignmentConflictError as exc:
        raise HTTPException(status_code=409, detail="guardrail assignment already exists") from exc


@router.patch("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: UUID,
    payload: UpdateGuardrailAssignmentRequest,
    actor: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailAssignmentResponse:
    try:
        existing = await _get_assignment_or_404(
            assignment_id=assignment_id,
            scope=scope,
            db=db,
        )
        await _require_assignment_admin(
            user=actor,
            scope_type=existing.scope_type,
            team_id=existing.team_id,
            project_id=existing.project_id,
            virtual_key_id=existing.virtual_key_id,
            scope=scope,
            db=db,
        )
        scope_type, team_id, project_id, virtual_key_id = _guardrail_assignment_target(
            payload=payload,
            existing=existing,
        )
        if _guardrail_assignment_target_changed(payload):
            await _require_assignment_admin(
                user=actor,
                scope_type=scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                scope=scope,
                db=db,
            )
        return await facade.update_assignment(
            assignment_id=assignment_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except GuardrailAssignmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail assignment not found") from exc
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc
    except GuardrailAssignmentTargetNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="guardrail assignment target not found",
        ) from exc
    except GuardrailAssignmentConflictError as exc:
        raise HTTPException(status_code=409, detail="guardrail assignment already exists") from exc


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(
    assignment_id: UUID,
    actor: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        existing = await _get_assignment_or_404(
            assignment_id=assignment_id,
            scope=scope,
            db=db,
        )
        await _require_assignment_admin(
            user=actor,
            scope_type=existing.scope_type,
            team_id=existing.team_id,
            project_id=existing.project_id,
            virtual_key_id=existing.virtual_key_id,
            scope=scope,
            db=db,
        )
        await facade.delete_assignment(
            assignment_id=assignment_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except GuardrailAssignmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail assignment not found") from exc


@router.get("/assignments/{assignment_id}/impact")
async def get_assignment_impact(
    assignment_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
) -> GuardrailImpactResponse:
    try:
        return await facade.get_assignment_impact(
            assignment_id=assignment_id,
            scope=scope,
            db=db,
            actor=actor,
        )
    except GuardrailAssignmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail assignment not found") from exc


@router.get("/events")
async def list_events(
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
    decision: str | None = None,
    phase: str | None = None,
    policy_id: UUID | None = None,
    rule_id: UUID | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    pool_id: UUID | None = None,
    model: str | None = None,
    limit: int = 50,
) -> list[GuardrailEventResponse]:
    return await facade.list_events(
        scope=scope,
        decision=decision,
        phase=phase,
        policy_id=policy_id,
        rule_id=rule_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        pool_id=pool_id,
        model=model,
        limit=min(max(limit, 1), 200),
        actor=actor,
        db=db,
    )


@router.post("/simulate")
async def simulate_guardrails(
    payload: GuardrailSimulationRequest,
    scope: RequestScope,
    db: DatabaseSession,
    actor: GuardrailViewer,
) -> GuardrailSimulationResponse:
    try:
        return await facade.simulate(payload=payload, scope=scope, db=db, actor=actor)
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc


async def _get_assignment_or_404(
    *,
    assignment_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> GuardrailAssignmentResponse:
    assignments = await facade.list_assignments(scope=scope, db=db)
    for assignment in assignments:
        if assignment.id == assignment_id:
            return assignment
    raise GuardrailAssignmentNotFoundError


def _guardrail_assignment_target(
    *,
    payload: UpdateGuardrailAssignmentRequest,
    existing: GuardrailAssignmentResponse,
) -> tuple[str, UUID | None, UUID | None, UUID | None]:
    scope_type = payload.scope_type or existing.scope_type
    if scope_type == "team":
        return scope_type, payload.team_id or existing.team_id, None, None
    if scope_type == "project":
        return scope_type, None, payload.project_id or existing.project_id, None
    if scope_type == "virtual_key":
        return scope_type, None, None, payload.virtual_key_id or existing.virtual_key_id
    return scope_type, None, None, None


def _guardrail_assignment_target_changed(payload: UpdateGuardrailAssignmentRequest) -> bool:
    return any(
        field in payload.model_fields_set
        for field in ("scope_type", "team_id", "project_id", "virtual_key_id")
    )


async def _require_assignment_admin(
    *,
    user: AuthenticatedUser,
    scope_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> None:
    try:
        await authorization_facade.require(
            actor=user,
            permission=Permissions.GUARDRAILS_ASSIGN,
            target=AuthorizationTarget.assignment_scope(
                scope_type=scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
            ),
            scope=scope,
            db=db,
        )
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
