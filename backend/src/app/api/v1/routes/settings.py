from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_permission
from app.core.config import settings
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.settings import facade
from app.modules.settings.schemas import (
    GatewayMetadataResponse,
    OrganizationSettingsResponse,
    UpdateOrganizationSettingsRequest,
)

router = APIRouter(prefix="/settings", tags=["settings"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
SettingsViewer = Annotated[AuthenticatedUser, Depends(require_permission("settings.view"))]
SettingsAdmin = Annotated[AuthenticatedUser, Depends(require_permission("settings.manage"))]
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
        raise HTTPException(status_code=413, detail="logo image is too large")
    # Derive the type from the actual bytes (magic number), not the client-supplied
    # content-type, so a non-image / polyglot payload cannot be stored as org_logo.*.
    extension = _detect_image_extension(content)
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


def _detect_image_extension(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None
