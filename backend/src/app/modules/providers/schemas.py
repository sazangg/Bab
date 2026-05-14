from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    is_active: bool | None = None


class CreateProviderCredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1)
    routing_policy: str = Field(default="priority", max_length=100)
    priority: int = Field(default=100, ge=0)


class UpdateProviderCredentialRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1)
    routing_policy: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProviderCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    created_by: UUID | None
    name: str
    key_prefix: str
    routing_policy: str
    priority: int
    health_status: str
    last_validation_error: str | None
    last_successful_request_at: datetime | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TestProviderCredentialResponse(BaseModel):
    id: UUID
    health_status: str
    last_validation_error: str | None = None
    last_successful_request_at: datetime | None = None


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

