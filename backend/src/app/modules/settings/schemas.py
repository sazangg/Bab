from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    organization_name: str
    organization_logo_url: str | None
    public_base_url: str | None
    default_request_timeout_seconds: int
    default_retry_count: int
    default_max_body_bytes: int
    default_model_sync_mode: str
    default_virtual_key_expiration_days: int | None
    usage_retention_days: int | None = None
    activity_retention_days: int | None = None
    virtual_key_prefix: str
    allow_secret_copy: bool
    created_at: datetime
    updated_at: datetime


class UpdateOrganizationSettingsRequest(BaseModel):
    organization_name: str | None = Field(default=None, min_length=1, max_length=255)
    organization_logo_url: str | None = Field(default=None, max_length=500)
    public_base_url: str | None = Field(default=None, max_length=500)
    default_request_timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    default_retry_count: int | None = Field(default=None, ge=0, le=10)
    default_max_body_bytes: int | None = Field(default=None, ge=1_024, le=100_000_000)
    default_model_sync_mode: str | None = Field(
        default=None,
        pattern="^(merge|replace|disabled)$",
    )
    default_virtual_key_expiration_days: int | None = Field(default=None, ge=1, le=3650)
    virtual_key_prefix: str | None = Field(default=None, min_length=1, max_length=32)
    allow_secret_copy: bool | None = None

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlparse(stripped)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("public_base_url must be a gateway origin URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public_base_url must be a gateway origin URL")
        return stripped.rstrip("/")
