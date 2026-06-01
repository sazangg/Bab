from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_scope, require_permission
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    CredentialPoolCredentialResponse,
    CredentialPoolResponse,
    ModelOfferingPageResponse,
    ModelOfferingResponse,
    ProviderCredentialResponse,
    ProviderResponse,
    SyncModelOfferingsRequest,
    TestModelOfferingRequest,
    TestModelOfferingResponse,
    TestProviderCredentialResponse,
    UpdateCredentialPoolCredentialRequest,
    UpdateCredentialPoolRequest,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
    UpdateProviderRequest,
)
from app.modules.settings import facade as settings_facade

router = APIRouter(prefix="/providers", tags=["providers"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
ProviderViewer = Annotated[AuthenticatedUser, Depends(require_permission("providers.view"))]
ProviderAdmin = Annotated[AuthenticatedUser, Depends(require_permission("providers.manage"))]


@router.get("")
async def list_providers(
    scope: RequestScope,
    db: DatabaseSession,
    _: ProviderViewer,
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
    _: ProviderViewer,
) -> ProviderResponse:
    try:
        return await facade.get_provider(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.get("/{provider_id}/pools")
async def list_credential_pools(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: ProviderViewer,
) -> list[CredentialPoolResponse]:
    try:
        return await facade.list_credential_pools(provider_id=provider_id, scope=scope, db=db)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.post("/{provider_id}/pools", status_code=status.HTTP_201_CREATED)
async def create_credential_pool(
    provider_id: UUID,
    payload: CreateCredentialPoolRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CredentialPoolResponse:
    try:
        return await facade.create_credential_pool(
            provider_id=provider_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc


@router.patch("/{provider_id}/pools/{pool_id}")
async def update_credential_pool(
    provider_id: UUID,
    pool_id: UUID,
    payload: UpdateCredentialPoolRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CredentialPoolResponse:
    try:
        return await facade.update_credential_pool(
            provider_id=provider_id,
            pool_id=pool_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="credential pool not found") from exc


@router.get("/{provider_id}/pools/{pool_id}/credentials")
async def list_credential_pool_credentials(
    provider_id: UUID,
    pool_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: ProviderViewer,
) -> list[CredentialPoolCredentialResponse]:
    try:
        return await facade.list_credential_pool_credentials(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="credential pool not found") from exc


@router.post("/{provider_id}/pools/{pool_id}/credentials", status_code=status.HTTP_201_CREATED)
async def add_credential_pool_credential(
    provider_id: UUID,
    pool_id: UUID,
    payload: AddCredentialPoolCredentialRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CredentialPoolCredentialResponse:
    try:
        return await facade.add_credential_pool_credential(
            provider_id=provider_id,
            pool_id=pool_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="credential pool or credential not found",
        ) from exc


@router.patch("/{provider_id}/pools/{pool_id}/credentials/{pool_credential_id}")
async def update_credential_pool_credential(
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    payload: UpdateCredentialPoolCredentialRequest,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> CredentialPoolCredentialResponse:
    try:
        return await facade.update_credential_pool_credential(
            provider_id=provider_id,
            pool_id=pool_id,
            pool_credential_id=pool_credential_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pool credential not found") from exc


@router.delete(
    "/{provider_id}/pools/{pool_id}/credentials/{pool_credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_credential_pool_credential(
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.delete_credential_pool_credential(
            provider_id=provider_id,
            pool_id=pool_id,
            pool_credential_id=pool_credential_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pool credential not found") from exc


@router.get("/{provider_id}/credentials")
async def list_provider_credentials(
    provider_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: ProviderViewer,
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
    _: ProviderViewer,
    search: str | None = Query(default=None, min_length=1, max_length=255),
    modality: str | None = Query(default=None, min_length=1, max_length=255),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=1000),
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


@router.post("/{provider_id}/offerings/{model_offering_id}/test")
async def test_model_offering(
    provider_id: UUID,
    model_offering_id: UUID,
    actor: ProviderAdmin,
    scope: RequestScope,
    db: DatabaseSession,
    payload: TestModelOfferingRequest | None = None,
) -> TestModelOfferingResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            return await facade.test_model_offering(
                provider_id=provider_id,
                model_offering_id=model_offering_id,
                payload=payload or TestModelOfferingRequest(),
                actor=actor,
                scope=scope,
                db=db,
                http_client=http_client,
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="model offering not found") from exc
    except ProviderCredentialRequiredError as exc:
        raise HTTPException(status_code=400, detail="active provider credential required") from exc


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
        org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
        provider = await facade.get_provider(provider_id=provider_id, scope=scope, db=db)
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
                sync_mode=provider.model_sync_mode or org_settings.default_model_sync_mode,
            )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except ProviderCredentialRequiredError as exc:
        raise HTTPException(status_code=400, detail="active provider credential required") from exc
    except ProviderUpstreamError as exc:
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail="model sync is disabled") from exc
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
