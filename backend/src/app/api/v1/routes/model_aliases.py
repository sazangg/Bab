from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade
from app.modules.keys.errors import ModelAliasAlreadyExistsError, ModelAliasNotFoundError
from app.modules.keys.schemas import (
    CreateModelAliasRequest,
    ModelAliasResponse,
    UpdateModelAliasRequest,
)
from app.modules.providers.errors import ProviderNotFoundError

router = APIRouter(prefix="/model-aliases", tags=["model-aliases"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
ModelAliasAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_model_aliases(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ModelAliasResponse]:
    return await facade.list_model_aliases(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_model_alias(
    payload: CreateModelAliasRequest,
    actor: ModelAliasAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ModelAliasResponse:
    try:
        return await facade.create_model_alias(payload=payload, actor=actor, scope=scope, db=db)
    except ModelAliasAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="model alias already exists") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{alias_id}")
async def update_model_alias(
    alias_id: UUID,
    payload: UpdateModelAliasRequest,
    actor: ModelAliasAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ModelAliasResponse:
    try:
        return await facade.update_model_alias(
            alias_id=alias_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ModelAliasNotFoundError as exc:
        raise HTTPException(status_code=404, detail="model alias not found") from exc
    except ModelAliasAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="model alias already exists") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.delete("/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_model_alias(
    alias_id: UUID,
    actor: ModelAliasAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_model_alias(alias_id=alias_id, actor=actor, scope=scope, db=db)
    except ModelAliasNotFoundError as exc:
        raise HTTPException(status_code=404, detail="model alias not found") from exc
