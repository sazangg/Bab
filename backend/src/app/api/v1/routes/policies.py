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
from app.modules.keys.errors import (
    InvalidVirtualKeyError,
    OrganizationInactiveError,
    ProjectAccessUnavailableError,
    ProjectInactiveError,
    VirtualKeyNotFoundError,
)
from app.modules.policies import facade
from app.modules.policies.errors import (
    PolicyAssignmentConflictError,
    PolicyNotFoundError,
    PolicyPermissionError,
    PolicyValidationError,
)
from app.modules.policies.schemas import (
    AccessPolicyOptionsResponse,
    AccessPolicyResponse,
    CreateAccessPolicyRequest,
    CreateLimitPolicyRequest,
    CreateLimitPolicyRuleRequest,
    CreatePolicyAssignmentRequest,
    CreateScopedPolicyAssignmentRequest,
    LimitPolicyResponse,
    LimitPolicyRuleResponse,
    PolicyAssignmentResponse,
    PolicyImpactResponse,
    ScopedPolicyAssignmentResponse,
    UpdateAccessPolicyRequest,
    UpdateLimitPolicyRequest,
    UpdateLimitPolicyRuleRequest,
    UpdatePolicyAssignmentRequest,
)
from app.modules.policy_simulation.schemas import (
    PolicySimulationRequest,
    PolicySimulationResponse,
)
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceAccessDeniedError

router = APIRouter(prefix="/policies", tags=["policies"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
ScopedPolicyViewer = Annotated[
    AuthenticatedUser,
    Depends(require_permission_or_scoped_admin("policies.view")),
]
PolicyAdmin = Annotated[AuthenticatedUser, Depends(require_permission("policies.manage"))]
AssignmentActor = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("/access")
async def list_access_policies(
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[AccessPolicyResponse]:
    return await facade.list_access_policies(scope=scope, db=db, actor=_user)


@router.post("/access", status_code=status.HTTP_201_CREATED)
async def create_access_policy(
    payload: CreateAccessPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.create_access_policy(payload=payload, scope=scope, db=db, actor=_user)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid access policy route") from exc


@router.get("/access/{policy_id}")
async def get_access_policy(
    policy_id: UUID,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.get_access_policy(policy_id=policy_id, scope=scope, db=db, actor=_user)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.patch("/access/{policy_id}")
async def update_access_policy(
    policy_id: UUID,
    payload: UpdateAccessPolicyRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> AccessPolicyResponse:
    try:
        return await facade.update_access_policy(
            policy_id=policy_id, payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyAssignmentConflictError as exc:
        raise HTTPException(status_code=409, detail="policy assignment conflict") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid access policy route") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.delete("/access/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access_policy(
    policy_id: UUID,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_access_policy(policy_id=policy_id, scope=scope, db=db, actor=_user)
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.get("/access/{policy_id}/impact")
async def get_access_policy_impact(
    policy_id: UUID,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyImpactResponse:
    try:
        return await facade.get_access_policy_impact(
            policy_id=policy_id, scope=scope, db=db, actor=_user
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="access policy not found") from exc


@router.get("/access-options")
async def get_access_policy_options(
    _user: ScopedPolicyViewer,
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
        await _require_assignment_admin(
            user=_user,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            scope=scope,
            db=db,
        )
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


@router.post("/simulations")
async def simulate_policies(
    payload: PolicySimulationRequest,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicySimulationResponse:
    try:
        return await facade.simulate_active_policies(
            payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid policy simulation draft") from exc
    except (VirtualKeyNotFoundError, InvalidVirtualKeyError) as exc:
        raise HTTPException(status_code=404, detail="virtual key not found") from exc
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except OrganizationInactiveError as exc:
        raise HTTPException(status_code=403, detail="organization is inactive") from exc
    except ProjectInactiveError as exc:
        raise HTTPException(status_code=403, detail="project is inactive") from exc
    except ProjectAccessUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/limits")
async def list_limit_policies(
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[LimitPolicyResponse]:
    return await facade.list_limit_policies(scope=scope, db=db, actor=_user)


@router.post("/limits", status_code=status.HTTP_201_CREATED)
async def create_limit_policy(
    payload: CreateLimitPolicyRequest,
    _user: PolicyAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.create_limit_policy(payload=payload, scope=scope, db=db, actor=_user)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy filter") from exc


@router.get("/limits/{policy_id}")
async def get_limit_policy(
    policy_id: UUID,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.get_limit_policy(policy_id=policy_id, scope=scope, db=db, actor=_user)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc


@router.patch("/limits/{policy_id}")
async def update_limit_policy(
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyResponse:
    try:
        return await facade.update_limit_policy(
            policy_id=policy_id, payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy filter") from exc


@router.delete("/limits/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_limit_policy(
    policy_id: UUID,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_limit_policy(policy_id=policy_id, scope=scope, db=db, actor=_user)
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc


@router.post("/limits/{policy_id}/rules", status_code=status.HTTP_201_CREATED)
async def create_limit_policy_rule(
    policy_id: UUID,
    payload: CreateLimitPolicyRuleRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyRuleResponse:
    try:
        return await facade.create_limit_policy_rule(
            policy_id=policy_id, payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy rule") from exc


@router.patch("/limits/rules/{rule_id}")
async def update_limit_policy_rule(
    rule_id: UUID,
    payload: UpdateLimitPolicyRuleRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> LimitPolicyRuleResponse:
    try:
        return await facade.update_limit_policy_rule(
            rule_id=rule_id, payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy rule not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid limit policy rule") from exc


@router.delete("/limits/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_limit_policy_rule(
    rule_id: UUID,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_limit_policy_rule(rule_id=rule_id, scope=scope, db=db, actor=_user)
    except PolicyPermissionError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy rule not found") from exc


@router.get("/limits/{policy_id}/impact")
async def get_limit_policy_impact(
    policy_id: UUID,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyImpactResponse:
    try:
        return await facade.get_limit_policy_impact(
            policy_id=policy_id, scope=scope, db=db, actor=_user
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy not found") from exc


@router.get("/limits/rules/{rule_id}/impact")
async def get_limit_policy_rule_impact(
    rule_id: UUID,
    _user: ScopedPolicyViewer,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyImpactResponse:
    try:
        return await facade.get_limit_policy_rule_impact(
            rule_id=rule_id, scope=scope, db=db, actor=_user
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="limit policy rule not found") from exc


@router.get("/assignments")
async def list_policy_assignments(
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[PolicyAssignmentResponse]:
    return await facade.list_policy_assignments(scope=scope, db=db, actor=_user)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_policy_assignment(
    payload: CreatePolicyAssignmentRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyAssignmentResponse:
    try:
        await _require_assignment_admin(
            user=_user,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            scope=scope,
            db=db,
        )
        return await facade.create_policy_assignment(
            payload=payload,
            scope=scope,
            db=db,
            actor=_user,
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy not found") from exc
    except PolicyAssignmentConflictError as exc:
        raise HTTPException(status_code=409, detail="policy assignment already exists") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid policy assignment") from exc


@router.post("/assignments/scoped-policy", status_code=status.HTTP_201_CREATED)
async def create_scoped_policy_assignment(
    payload: CreateScopedPolicyAssignmentRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> ScopedPolicyAssignmentResponse:
    try:
        await _require_assignment_admin(
            user=_user,
            scope_type=payload.scope_type,
            team_id=payload.team_id,
            project_id=payload.project_id,
            virtual_key_id=payload.virtual_key_id,
            scope=scope,
            db=db,
        )
        return await facade.create_scoped_policy_assignment(
            payload=payload,
            scope=scope,
            db=db,
            actor=_user,
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy scope not found") from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid scoped policy assignment") from exc


@router.patch("/assignments/{assignment_id}")
async def update_policy_assignment(
    assignment_id: UUID,
    payload: UpdatePolicyAssignmentRequest,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> PolicyAssignmentResponse:
    try:
        existing = await _get_policy_assignment_or_404(
            assignment_id=assignment_id,
            scope=scope,
            db=db,
        )
        await _require_assignment_admin(
            user=_user,
            scope_type=existing.scope_type,
            team_id=existing.team_id,
            project_id=existing.project_id,
            virtual_key_id=existing.virtual_key_id,
            scope=scope,
            db=db,
        )
        return await facade.update_policy_assignment(
            assignment_id=assignment_id, payload=payload, scope=scope, db=db, actor=_user
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy assignment not found") from exc


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy_assignment(
    assignment_id: UUID,
    _user: AssignmentActor,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        existing = await _get_policy_assignment_or_404(
            assignment_id=assignment_id,
            scope=scope,
            db=db,
        )
        await _require_assignment_admin(
            user=_user,
            scope_type=existing.scope_type,
            team_id=existing.team_id,
            project_id=existing.project_id,
            virtual_key_id=existing.virtual_key_id,
            scope=scope,
            db=db,
        )
        await facade.delete_policy_assignment(
            assignment_id=assignment_id, scope=scope, db=db, actor=_user
        )
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy assignment not found") from exc


async def _get_policy_assignment_or_404(
    *, assignment_id: UUID, scope: Scope, db: AsyncSession
) -> PolicyAssignmentResponse:
    assignments = await facade.list_policy_assignments(scope=scope, db=db)
    for assignment in assignments:
        if assignment.id == assignment_id:
            return assignment
    raise PolicyNotFoundError


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
        await workspace_facade.require_assignment_admin(
            actor=user,
            scope=scope,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc
