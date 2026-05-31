from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_scope, require_permission
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
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
    GuardrailPolicyResponse,
    GuardrailSimulationRequest,
    GuardrailSimulationResponse,
    UpdateGuardrailAssignmentRequest,
    UpdateGuardrailPolicyRequest,
)

router = APIRouter(prefix="/guardrails", tags=["guardrails"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
GuardrailViewer = Annotated[AuthenticatedUser, Depends(require_permission("guardrails.view"))]
GuardrailAdmin = Annotated[AuthenticatedUser, Depends(require_permission("guardrails.manage"))]


@router.get("/policies")
async def list_policies(
    scope: RequestScope,
    db: DatabaseSession,
    _: GuardrailViewer,
) -> list[GuardrailPolicyResponse]:
    return await facade.list_policies(scope=scope, db=db)


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


@router.get("/assignments")
async def list_assignments(
    scope: RequestScope,
    db: DatabaseSession,
    _: GuardrailViewer,
) -> list[GuardrailAssignmentResponse]:
    return await facade.list_assignments(scope=scope, db=db)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: CreateGuardrailAssignmentRequest,
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailAssignmentResponse:
    try:
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
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> GuardrailAssignmentResponse:
    try:
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
    actor: GuardrailAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_assignment(
            assignment_id=assignment_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except GuardrailAssignmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail assignment not found") from exc


@router.get("/events")
async def list_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: GuardrailViewer,
    decision: str | None = None,
    phase: str | None = None,
    policy_id: UUID | None = None,
    rule_id: UUID | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allocation_id: UUID | None = None,
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
        allocation_id=allocation_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        pool_id=pool_id,
        model=model,
        limit=min(max(limit, 1), 200),
        db=db,
    )


@router.post("/simulate")
async def simulate_guardrails(
    payload: GuardrailSimulationRequest,
    scope: RequestScope,
    db: DatabaseSession,
    _: GuardrailViewer,
) -> GuardrailSimulationResponse:
    try:
        return await facade.simulate(payload=payload, scope=scope, db=db)
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="guardrail policy not found") from exc
