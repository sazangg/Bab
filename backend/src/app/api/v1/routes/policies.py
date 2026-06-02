from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_scope, require_permission
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.policies import facade
from app.modules.policies.errors import PolicyNotFoundError, PolicyValidationError
from app.modules.policies.schemas import (
    AccessPolicyOptionsResponse,
    AccessPolicyResponse,
    AccessPolicyRouteResponse,
    CreateAccessPolicyRequest,
    CreateAccessPolicyRouteRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    LimitPolicyResponse,
    LimitPolicyRuleResponse,
    PolicyAssignmentResponse,
    UpdateAccessPolicyRequest,
    UpdateAccessPolicyRouteRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)

router = APIRouter(prefix="/policies", tags=["policies"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
PolicyViewer = Annotated[AuthenticatedUser, Depends(require_permission("policies.view"))]
PolicyAdmin = Annotated[AuthenticatedUser, Depends(require_permission("policies.manage"))]


@router.get("/access")
async def list_access_policies(
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[AccessPolicyResponse]:
    return await facade.list_access_policies(scope=scope, db=db)


@router.post("/access", status_code=status.HTTP_201_CREATED)
async def create_access_policy(
    payload: CreateAccessPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.create_access_policy(payload=payload, scope=scope, db=db)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid access policy route") from exc


@router.get("/access/{policy_id}")
async def get_access_policy(
    policy_id: UUID,
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.get_access_policy(policy_id=policy_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.patch("/access/{policy_id}")
async def update_access_policy(
    policy_id: UUID,
    payload: UpdateAccessPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.update_access_policy(
            policy_id=policy_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.delete("/access/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access_policy(
    policy_id: UUID,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_access_policy(policy_id=policy_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.post("/access/{policy_id}/routes", status_code=status.HTTP_201_CREATED)
async def create_access_policy_route(
    policy_id: UUID,
    payload: CreateAccessPolicyRouteRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyRouteResponse:
    try:
        return await facade.create_access_policy_route(
            policy_id=policy_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid access policy route") from exc


@router.patch("/access/routes/{route_id}")
async def update_access_policy_route(
    route_id: UUID,
    payload: UpdateAccessPolicyRouteRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyRouteResponse:
    try:
        return await facade.update_access_policy_route(
            route_id=route_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy route not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid access policy route") from exc


@router.delete("/access/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access_policy_route(
    route_id: UUID,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_access_policy_route(route_id=route_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy route not found") from exc


@router.get("/access-options")
async def get_access_policy_options(
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
    scope_type: str,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    exclude_policy_id: UUID | None = None,
) -> AccessPolicyOptionsResponse:
    if scope_type not in {"org", "team", "project", "virtual_key"}:
        raise HTTPException(status_code=422, detail="invalid scope type")
    try:
        return await facade.get_access_policy_options(
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            exclude_policy_id=exclude_policy_id,
            scope=scope,
            db=db,
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy scope not found") from exc


@router.get("/limits")
async def list_limit_policies(
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[LimitPolicyResponse]:
    return await facade.list_limit_policies(scope=scope, db=db)


@router.post("/limits", status_code=status.HTTP_201_CREATED)
async def create_limit_policy(
    payload: CreateLimitPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.create_limit_policy(payload=payload, scope=scope, db=db)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy filter") from exc


@router.get("/limits/{policy_id}")
async def get_limit_policy(
    policy_id: UUID,
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.get_limit_policy(policy_id=policy_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc


@router.patch("/limits/{policy_id}")
async def update_limit_policy(
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.update_limit_policy(
            policy_id=policy_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy filter") from exc


@router.delete("/limits/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_limit_policy(
    policy_id: UUID,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_limit_policy(policy_id=policy_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc


@router.post("/limits/{policy_id}/rules", status_code=status.HTTP_201_CREATED)
async def create_limit_policy_rule(
    policy_id: UUID,
    payload: CreateLimitPolicyRuleRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyRuleResponse:
    try:
        return await facade.create_limit_policy_rule(
            policy_id=policy_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy rule") from exc


@router.patch("/limits/rules/{rule_id}")
async def update_limit_policy_rule(
    rule_id: UUID,
    payload: UpdateLimitPolicyRuleRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyRuleResponse:
    try:
        return await facade.update_limit_policy_rule(
            rule_id=rule_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy rule not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy rule") from exc


@router.delete("/limits/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_limit_policy_rule(
    rule_id: UUID,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_limit_policy_rule(rule_id=rule_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy rule not found") from exc


@router.get("/assignments")
async def list_policy_assignments(
    _user: PolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[PolicyAssignmentResponse]:
    return await facade.list_policy_assignments(scope=scope, db=db)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_policy_assignment(
    payload: CreatePolicyAssignmentRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyAssignmentResponse:
    try:
        return await facade.create_policy_assignment(payload=payload, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid policy assignment") from exc


@router.patch("/assignments/{assignment_id}")
async def update_policy_assignment(
    assignment_id: UUID,
    payload: UpdatePolicyAssignmentRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyAssignmentResponse:
    try:
        return await facade.update_policy_assignment(
            assignment_id=assignment_id, payload=payload, scope=scope, db=db
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy assignment not found") from exc


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy_assignment(
    assignment_id: UUID,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_policy_assignment(assignment_id=assignment_id, scope=scope, db=db)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy assignment not found") from exc
