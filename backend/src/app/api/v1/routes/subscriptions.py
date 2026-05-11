from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade
from app.modules.keys.errors import SubscriptionNotFoundError
from app.modules.keys.schemas import (
    AttachSubscriptionProviderKeyRequest,
    CreateSubscriptionRequest,
    SetSubscriptionModelAccessRequest,
    SubscriptionModelAccessResponse,
    SubscriptionProviderKeyResponse,
    SubscriptionResponse,
)
from app.modules.providers.errors import ProviderNotFoundError

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
SubscriptionAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_subscriptions(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[SubscriptionResponse]:
    return await facade.list_subscriptions(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: CreateSubscriptionRequest,
    actor: SubscriptionAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> SubscriptionResponse:
    return await facade.create_subscription(payload=payload, actor=actor, scope=scope, db=db)


@router.get("/{subscription_id}/provider-keys")
async def list_subscription_provider_keys(
    subscription_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[SubscriptionProviderKeyResponse]:
    try:
        return await facade.list_subscription_provider_keys(
            subscription_id=subscription_id,
            scope=scope,
            db=db,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subscription not found") from exc


@router.post("/{subscription_id}/provider-keys", status_code=status.HTTP_201_CREATED)
async def attach_provider_key_to_subscription(
    subscription_id: UUID,
    payload: AttachSubscriptionProviderKeyRequest,
    actor: SubscriptionAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> SubscriptionProviderKeyResponse:
    try:
        return await facade.attach_provider_key_to_subscription(
            subscription_id=subscription_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subscription not found") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider key not found") from exc


@router.get("/{subscription_id}/model-access")
async def list_subscription_model_access(
    subscription_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[SubscriptionModelAccessResponse]:
    try:
        return await facade.list_subscription_model_access(
            subscription_id=subscription_id,
            scope=scope,
            db=db,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subscription not found") from exc


@router.put("/{subscription_id}/model-access")
async def set_subscription_model_access(
    subscription_id: UUID,
    payload: SetSubscriptionModelAccessRequest,
    actor: SubscriptionAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[SubscriptionModelAccessResponse]:
    try:
        return await facade.set_subscription_model_access(
            subscription_id=subscription_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="subscription not found") from exc
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider model not found") from exc
