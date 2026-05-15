from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProviderCredentialRoutingPolicy(StrEnum):
    priority = "priority"
    round_robin = "round_robin"
    least_recently_used = "least_recently_used"
    health_based = "health_based"
    weighted = "weighted"
    fallback = "fallback"


class CreateProviderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl
    api_key: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=1000)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_body_bytes: int | None = Field(default=None, ge=1)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    circuit_breaker_policy: dict[str, Any] = Field(default_factory=dict)
    max_concurrent_requests: int | None = Field(default=None, ge=1)
    credential_routing_policy: ProviderCredentialRoutingPolicy = (
        ProviderCredentialRoutingPolicy.priority
    )


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=1000)
    capabilities: dict[str, bool] | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_body_bytes: int | None = Field(default=None, ge=1)
    retry_policy: dict[str, Any] | None = None
    fallback_policy: dict[str, Any] | None = None
    circuit_breaker_policy: dict[str, Any] | None = None
    max_concurrent_requests: int | None = Field(default=None, ge=1)
    credential_routing_policy: ProviderCredentialRoutingPolicy | None = None
    is_active: bool | None = None


class CreateProviderCredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1)
    priority: int = Field(default=100, ge=0)


class UpdateProviderCredentialRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1)
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProviderCredentialPriorityUpdate(BaseModel):
    provider_credential_id: UUID
    priority: int = Field(ge=0)


class ReorderProviderCredentialsRequest(BaseModel):
    updates: list[ProviderCredentialPriorityUpdate] = Field(min_length=1)


class ProviderCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    created_by: UUID | None
    name: str
    key_prefix: str
    priority: int
    health_status: str
    last_validation_error: str | None
    last_successful_request_at: datetime | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProviderCredentialSummary(BaseModel):
    total: int = 0
    active: int = 0
    valid: int = 0
    degraded: int = 0
    invalid: int = 0
    unchecked: int = 0


class TestProviderCredentialResponse(BaseModel):
    id: UUID
    health_status: str
    last_validation_error: str | None = None
    last_successful_request_at: datetime | None = None


class TestModelOfferingRequest(BaseModel):
    provider_credential_id: UUID | None = None


class TestModelOfferingResponse(BaseModel):
    id: UUID
    provider_credential_id: UUID | None = None
    health_status: str
    last_validation_error: str | None = None
    upstream_status_code: int | None = None


class CreateModelOfferingRequest(BaseModel):
    provider_model_name: str = Field(min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=100)
    modality: str = Field(default="text", max_length=100)
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])
    capabilities: dict[str, bool] = Field(default_factory=dict)
    context_window: int | None = Field(default=None, ge=1)
    input_price_per_million_tokens: int | None = Field(default=None, ge=0)
    output_price_per_million_tokens: int | None = Field(default=None, ge=0)
    cached_input_price_per_million_tokens: int | None = Field(default=None, ge=0)
    rate_limit_hints: dict[str, Any] = Field(default_factory=dict)


class UpdateModelOfferingRequest(BaseModel):
    provider_model_name: str | None = Field(default=None, min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=100)
    modality: str | None = Field(default=None, max_length=100)
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None
    capabilities: dict[str, bool] | None = None
    context_window: int | None = Field(default=None, ge=1)
    input_price_per_million_tokens: int | None = Field(default=None, ge=0)
    output_price_per_million_tokens: int | None = Field(default=None, ge=0)
    cached_input_price_per_million_tokens: int | None = Field(default=None, ge=0)
    rate_limit_hints: dict[str, Any] | None = None
    is_active: bool | None = None


class ModelMetadataSyncMode(StrEnum):
    fill_missing = "fill_missing"
    overwrite_catalog = "overwrite_catalog"


class SyncModelOfferingsRequest(BaseModel):
    metadata_mode: ModelMetadataSyncMode = ModelMetadataSyncMode.fill_missing


class ModelOfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    provider_model_name: str
    alias: str | None
    version: str | None
    modality: str
    input_modalities: list[str]
    output_modalities: list[str]
    capabilities: dict[str, Any]
    context_window: int | None
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None
    cached_input_price_per_million_tokens: int | None
    rate_limit_hints: dict[str, Any]
    metadata_source: str
    metadata_last_synced_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ModelOfferingPageResponse(BaseModel):
    items: list[ModelOfferingResponse]
    total: int
    limit: int
    offset: int


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    slug: str | None
    base_url: str
    adapter_type: str
    display_name: str | None
    description: str | None
    capabilities: dict[str, Any]
    supported_integration: str
    request_timeout_seconds: int
    max_body_bytes: int | None
    retry_policy: dict[str, Any]
    fallback_policy: dict[str, Any]
    circuit_breaker_policy: dict[str, Any]
    max_concurrent_requests: int | None
    credential_routing_policy: str
    credential_summary: ProviderCredentialSummary = Field(default_factory=ProviderCredentialSummary)
    is_active: bool
    created_at: datetime
    updated_at: datetime

class ProviderChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    messages: list[dict[str, Any]] = Field(min_length=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ProviderChatCompletionResponse(BaseModel):
    status_code: int
    body: dict[str, Any]


class ProviderChatCompletionStream:
    def __init__(
        self,
        *,
        status_code: int,
        chunks: AsyncIterator[bytes],
        close: Callable[[], Awaitable[None]],
        media_type: str,
    ) -> None:
        self.status_code = status_code
        self.chunks = chunks
        self.close = close
        self.media_type = media_type

