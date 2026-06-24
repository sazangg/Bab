from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.settings.internal import repository
from app.modules.settings.schemas import (
    GatewayMetadataResponse,
    OrganizationSettingsResponse,
    UpdateOrganizationSettingsRequest,
)


async def get_organization_settings(
    *,
    scope: Scope,
    db: AsyncSession,
) -> OrganizationSettingsResponse:
    settings = await repository.get_settings(org_id=scope.org_id, db=db)
    if settings is None:
        org = await auth_facade.get_organization_identity(org_id=scope.org_id, db=db)
        settings = await repository.create_settings(
            org_id=scope.org_id,
            organization_name=org.name if org else env_settings.default_organization_name,
            default_max_body_bytes=env_settings.proxy_max_body_bytes,
            public_app_url=env_settings.public_app_url,
            db=db,
        )
        await db.commit()
    return _to_response(settings)


async def update_organization_settings(
    *,
    payload: UpdateOrganizationSettingsRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> OrganizationSettingsResponse:
    async with transaction(db):
        settings = await repository.get_settings(org_id=scope.org_id, db=db)
        if settings is None:
            org = await auth_facade.get_organization_identity(org_id=scope.org_id, db=db)
            settings = await repository.create_settings(
                org_id=scope.org_id,
                organization_name=org.name if org else env_settings.default_organization_name,
                default_max_body_bytes=env_settings.proxy_max_body_bytes,
                public_app_url=env_settings.public_app_url,
                db=db,
            )
        metadata = _build_update_metadata(settings=settings, payload=payload)
        for field in payload.model_fields_set:
            setattr(settings, field, getattr(payload, field))
        if "organization_name" in payload.model_fields_set and payload.organization_name:
            await auth_facade.update_organization_name(
                org_id=scope.org_id,
                name=payload.organization_name,
                db=db,
            )
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="settings",
            action="settings.updated",
            message="Updated organization settings.",
            db=db,
            metadata=metadata,
        )
    return _to_response(settings)


async def get_gateway_metadata(
    *,
    scope: Scope,
    db: AsyncSession,
) -> GatewayMetadataResponse:
    settings = await get_organization_settings(scope=scope, db=db)
    return GatewayMetadataResponse(
        organization_name=settings.organization_name,
        organization_logo_url=settings.organization_logo_url,
        public_base_url=settings.public_base_url,
        virtual_key_prefix=settings.virtual_key_prefix,
        default_virtual_key_expiration_days=settings.default_virtual_key_expiration_days,
        allow_secret_copy=settings.allow_secret_copy,
    )


def _to_response(settings) -> OrganizationSettingsResponse:
    response = OrganizationSettingsResponse.model_validate(settings)
    return response.model_copy(
        update={
            "usage_retention_days": env_settings.usage_retention_days,
            "activity_retention_days": env_settings.activity_retention_days,
            "deployment_max_body_bytes": env_settings.proxy_max_body_bytes,
        }
    )


SAFE_AUDIT_FIELDS = {
    "organization_name",
    "public_app_url",
    "public_base_url",
    "default_request_timeout_seconds",
    "default_retry_count",
    "default_max_body_bytes",
    "default_model_sync_mode",
    "default_virtual_key_expiration_days",
    "virtual_key_prefix",
    "allow_secret_copy",
    "organization_logo_url",
}


def _build_update_metadata(*, settings, payload: UpdateOrganizationSettingsRequest) -> dict:
    changes = {}
    for field in sorted(payload.model_fields_set):
        if field not in SAFE_AUDIT_FIELDS:
            continue
        old_value = getattr(settings, field)
        new_value = getattr(payload, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
    return {"changed_fields": list(changes), "changes": changes}
