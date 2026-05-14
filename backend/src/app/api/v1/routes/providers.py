from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.schemas import (
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ModelOfferingPageResponse,
    ModelOfferingResponse,
    ProviderCredentialResponse,
    ProviderResponse,
    SyncModelOfferingsRequest,
    TestProviderCredentialResponse,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
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


@router.get("/{provider_id}")
async def get_provider(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> ProviderResponse:
    try:
        return await facade.get_provider(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.get("/{provider_id}/credentials")
async def list_provider_credentials(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[ProviderCredentialResponse]:
    try:
        return await facade.list_provider_credentials(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.post("/{provider_id}/credentials", status_code=status.HTTP_201_CREATED)
async def create_provider_credential(
    provider_id: UUID,
    payload: CreateProviderCredentialRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderCredentialResponse:
    try:
        return await facade.create_provider_credential(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{provider_id}/credentials/{provider_credential_id}")
async def update_provider_credential(
    provider_id: UUID,
    provider_credential_id: UUID,
    payload: UpdateProviderCredentialRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProviderCredentialResponse:
    try:
        return await facade.update_provider_credential(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider credential not found") from exc


@router.post("/{provider_id}/credentials/{provider_credential_id}/test")
async def test_provider_credential(
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TestProviderCredentialResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            return await facade.test_provider_credential(
                provider_id=provider_id,
                provider_credential_id=provider_credential_id,
                actor=actor,
                scope=scope,
                db=db,
                http_client=http_client,
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider credential not found") from exc


@router.delete(
    "/{provider_id}/credentials/{provider_credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_provider_credential(
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_provider_credential(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider credential not found") from exc


@router.get("/{provider_id}/offerings")
async def list_model_offerings(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
    search: str | None = Query(default=None, min_length=1, max_length=255),
    modality: str | None = Query(default=None, min_length=1, max_length=255),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ModelOfferingPageResponse:
    try:
        return await facade.list_model_offerings(
            provider_id=provider_id,
            search=search,
            modalities=_parse_modalities(modality),
            is_active=is_active,
            limit=limit,
            offset=offset,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


def _parse_modalities(value: str | None) -> list[str] | None:
    if value is None:
        return None
    modalities = [item.strip() for item in value.split(",") if item.strip()]
    return modalities or None


@router.post("/{provider_id}/offerings", status_code=status.HTTP_201_CREATED)
async def create_model_offering(
    provider_id: UUID,
    payload: CreateModelOfferingRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ModelOfferingResponse:
    try:
        return await facade.create_model_offering(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{provider_id}/offerings/{model_offering_id}")
async def update_model_offering(
    provider_id: UUID,
    model_offering_id: UUID,
    payload: UpdateModelOfferingRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ModelOfferingResponse:
    try:
        return await facade.update_model_offering(
            provider_id=provider_id,
            model_offering_id=model_offering_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="model offering not found") from exc


@router.delete(
    "/{provider_id}/offerings/{model_offering_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_model_offering(
    provider_id: UUID,
    model_offering_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_model_offering(
            provider_id=provider_id,
            model_offering_id=model_offering_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="model offering not found") from exc


@router.post("/{provider_id}/offerings/sync")
async def sync_model_offerings(
    provider_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
    payload: SyncModelOfferingsRequest | None = None,
) -> list[ModelOfferingResponse]:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            return await facade.sync_model_offerings(
                provider_id=provider_id,
                actor=actor,
                scope=scope,
                db=db,
                http_client=http_client,
                metadata_mode=(
                    payload.metadata_mode
                    if payload is not None
                    else SyncModelOfferingsRequest().metadata_mode
                ),
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderCredentialRequiredError as exc:
        raise HTTPException(status_code=400, detail="active provider credential required") from exc
    except ProviderUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"model offering sync failed with upstream status {exc.status_code}",
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

