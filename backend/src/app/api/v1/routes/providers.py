from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade
from app.modules.providers.errors import (
    ProviderKeyRequiredError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.schemas import (
    CreateProviderKeyRequest,
    CreateProviderModelRequest,
    CreateProviderRequest,
    ProviderKeyResponse,
    ProviderModelResponse,
    ProviderResponse,
    TestProviderCredentialResponse,
    UpdateProviderKeyRequest,
    UpdateProviderModelRequest,
    UpdateProviderRequest,
)

router = APIRouter(prefix="/providers", tags=["providers"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
ProviderAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_providers(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProviderResponse]:
    return await facade.list_providers(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: CreateProviderRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderResponse:
    return await facade.create_provider(payload=payload, actor=actor, scope=scope, db=db)


@router.get("/{provider_id}/keys")
async def list_provider_keys(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProviderKeyResponse]:
    try:
        return await facade.list_provider_keys(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.post("/{provider_id}/keys", status_code=status.HTTP_201_CREATED)
async def create_provider_key(
    provider_id: UUID,
    payload: CreateProviderKeyRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderKeyResponse:
    try:
        return await facade.create_provider_key(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{provider_id}/keys/{provider_key_id}")
async def update_provider_key(
    provider_id: UUID,
    provider_key_id: UUID,
    payload: UpdateProviderKeyRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderKeyResponse:
    try:
        return await facade.update_provider_key(
            provider_id=provider_id,
            provider_key_id=provider_key_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider key not found") from exc


@router.post("/{provider_id}/keys/{provider_key_id}/test")
async def test_provider_credential(
    provider_id: UUID,
    provider_key_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TestProviderCredentialResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            return await facade.test_provider_credential(
                provider_id=provider_id,
                provider_key_id=provider_key_id,
                actor=actor,
                scope=scope,
                db=db,
                http_client=http_client,
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider key not found") from exc


@router.delete("/{provider_id}/keys/{provider_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_provider_key(
    provider_id: UUID,
    provider_key_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_provider_key(
            provider_id=provider_id,
            provider_key_id=provider_key_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider key not found") from exc


@router.get("/{provider_id}/models")
async def list_provider_models(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProviderModelResponse]:
    try:
        return await facade.list_provider_models(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.post("/{provider_id}/models", status_code=status.HTTP_201_CREATED)
async def create_provider_model(
    provider_id: UUID,
    payload: CreateProviderModelRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderModelResponse:
    try:
        return await facade.create_provider_model(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{provider_id}/models/{provider_model_id}")
async def update_provider_model(
    provider_id: UUID,
    provider_model_id: UUID,
    payload: UpdateProviderModelRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderModelResponse:
    try:
        return await facade.update_provider_model(
            provider_id=provider_id,
            provider_model_id=provider_model_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider model not found") from exc


@router.delete(
    "/{provider_id}/models/{provider_model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_provider_model(
    provider_id: UUID,
    provider_model_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_provider_model(
            provider_id=provider_id,
            provider_model_id=provider_model_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider model not found") from exc


@router.post("/{provider_id}/models/sync")
async def sync_provider_models(
    provider_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[ProviderModelResponse]:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            return await facade.sync_provider_models(
                provider_id=provider_id,
                actor=actor,
                scope=scope,
                db=db,
                http_client=http_client,
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderKeyRequiredError as exc:
        raise HTTPException(status_code=400, detail="active provider key required") from exc
    except ProviderUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"provider model sync failed with upstream status {exc.status_code}",
        ) from exc


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: UUID,
    payload: UpdateProviderRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderResponse:
    try:
        return await facade.update_provider(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_provider(
    provider_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_provider(provider_id=provider_id, actor=actor, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
