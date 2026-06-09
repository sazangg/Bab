from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.settings.internal import repository
from app.modules.settings.schemas import (
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
        org = await db.get(Organization, scope.org_id)
        settings = await repository.create_settings(
            org_id=scope.org_id,
            organization_name=org.name if org else env_settings.default_organization_name,
            default_max_body_bytes=env_settings.proxy_max_body_bytes,
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
            org = await db.get(Organization, scope.org_id)
            settings = await repository.create_settings(
                org_id=scope.org_id,
                organization_name=org.name if org else env_settings.default_organization_name,
                default_max_body_bytes=env_settings.proxy_max_body_bytes,
                db=db,
            )
        for field in payload.model_fields_set:
            setattr(settings, field, getattr(payload, field))
        if "organization_name" in payload.model_fields_set and payload.organization_name:
            org = await db.get(Organization, scope.org_id)
            if org is not None:
                org.name = payload.organization_name
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="settings",
            action="settings.updated",
            message="Updated organization settings.",
            db=db,
        )
    return _to_response(settings)


def _to_response(settings) -> OrganizationSettingsResponse:
    response = OrganizationSettingsResponse.model_validate(settings)
    return response.model_copy(
        update={
            "usage_retention_days": env_settings.usage_retention_days,
            "activity_retention_days": env_settings.activity_retention_days,
        }
    )
