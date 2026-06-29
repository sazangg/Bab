from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_permission
from app.core.config import settings
from app.core.database import Scope, get_db
from app.core.image_detection import detect_image_extension
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization.permissions import Permissions
from app.modules.settings import facade
from app.modules.settings.schemas import (
    GatewayMetadataResponse,
    OrganizationSettingsResponse,
    UpdateOrganizationSettingsRequest,
)

router = APIRouter(prefix="/settings", tags=["settings"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
SettingsViewer = Annotated[
    AuthenticatedUser,
    Depends(require_permission(Permissions.SETTINGS_VIEW)),
]
SettingsAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_permission(Permissions.SETTINGS_MANAGE)),
]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def get_settings(
    scope: RequestScope,
    db: DatabaseSession,
    _: SettingsViewer,
) -> OrganizationSettingsResponse:
    return await facade.get_organization_settings(scope=scope, db=db)


@router.get("/gateway-metadata")
async def get_gateway_metadata(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> GatewayMetadataResponse:
    return await facade.get_gateway_metadata(scope=scope, db=db)


@router.patch("")
async def update_settings(
    payload: UpdateOrganizationSettingsRequest,
    actor: SettingsAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> OrganizationSettingsResponse:
    return await facade.update_organization_settings(
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


@router.post("/organization-logo")
async def upload_organization_logo(
    file: Annotated[UploadFile, File()],
    actor: SettingsAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> OrganizationSettingsResponse:
    # Read at most the limit + 1 byte so an oversized upload is rejected without
    # buffering the whole (potentially huge) body into memory.
    content = await file.read(2_000_001)
    if len(content) > 2_000_000:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="logo image is too large",
        )
    # Derive the type from the actual bytes (magic number), not the client-supplied
    # content-type, so a non-image / polyglot payload cannot be stored as org_logo.*.
    extension = detect_image_extension(content)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="logo must be a valid png, jpg, or webp image",
        )
    org_asset_dir = Path(settings.assets_dir) / "organizations" / str(scope.org_id)
    org_asset_dir.mkdir(parents=True, exist_ok=True)
    for existing in org_asset_dir.glob("org_logo.*"):
        existing.unlink(missing_ok=True)
    logo_path = org_asset_dir / f"org_logo{extension}"
    logo_path.write_bytes(content)
    logo_url = f"/assets/organizations/{scope.org_id}/org_logo{extension}"
    return await facade.update_organization_settings(
        payload=UpdateOrganizationSettingsRequest(organization_logo_url=logo_url),
        actor=actor,
        scope=scope,
        db=db,
    )

