from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.limits import facade
from app.modules.limits.errors import LimitPolicyNotFoundError
from app.modules.limits.schemas import (
    CreateLimitPolicyRequest,
    LimitPolicyResponse,
    UpdateLimitPolicyRequest,
)

router = APIRouter(prefix="/limit-policies", tags=["limit-policies"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
LimitPolicyAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_limit_policies(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[LimitPolicyResponse]:
    return await facade.list_policies(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_limit_policy(
    payload: CreateLimitPolicyRequest,
    actor: LimitPolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.create_policy(payload=payload, actor=actor, scope=scope, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{policy_id}")
async def update_limit_policy(
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    actor: LimitPolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.update_policy(
            policy_id=policy_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except LimitPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_limit_policy(
    policy_id: UUID,
    actor: LimitPolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_policy(policy_id=policy_id, actor=actor, scope=scope, db=db)
    except LimitPolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
