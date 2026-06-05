from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool

StatusCode = Annotated[int, Field(ge=100, le=599, strict=True)]


class ProviderCredentialRoutingPolicy(StrEnum):
    priority = "priority"
    round_robin = "round_robin"
    least_recently_used = "least_recently_used"
    health_based = "health_based"
    weighted = "weighted"


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat: StrictBool = True
    embeddings: StrictBool = False
    vision: StrictBool = False
    tools: StrictBool = False
    json_mode: StrictBool = False
    streaming: StrictBool = True


class ProviderRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = True
    max_attempts: int = Field(default=3, ge=1, le=10, strict=True)
    backoff: str = Field(default="exponential", pattern="^(constant|linear|exponential)$")
    initial_delay_ms: int = Field(default=500, ge=0, le=60000, strict=True)
    max_delay_ms: int = Field(default=10000, ge=0, le=60000, strict=True)
    retry_on_status: list[StatusCode] = Field(
        default_factory=lambda: [408, 429, 500, 502, 503, 504],
    )


class ProviderCircuitBreakerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    failure_threshold_pct: int = Field(default=50, ge=0, le=100, strict=True)
    min_request_count: int = Field(default=20, ge=1, le=10000, strict=True)
    window_seconds: int = Field(default=60, ge=1, le=3600, strict=True)
    cooldown_seconds: int = Field(default=30, ge=1, le=3600, strict=True)


class CreateProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl
    description: str | None = Field(default=None, max_length=1000)
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    request_timeout_seconds: int | None = Field(default=None, ge=1, le=300, strict=True)
    max_body_bytes: int | None = Field(default=None, ge=1, strict=True)
    retry_policy: ProviderRetryPolicy | None = None
    model_sync_mode: str | None = Field(default=None, pattern="^(merge|replace|disabled)$")
    circuit_breaker_policy: ProviderCircuitBreakerPolicy = Field(
        default_factory=ProviderCircuitBreakerPolicy,
    )
    max_concurrent_requests: int | None = Field(default=None, ge=1, strict=True)


class UpdateProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=1000)
    capabilities: ProviderCapabilities | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=1, le=300, strict=True)
    max_body_bytes: int | None = Field(default=None, ge=1, strict=True)
    retry_policy: ProviderRetryPolicy | None = None
    model_sync_mode: str | None = Field(default=None, pattern="^(merge|replace|disabled)$")
    circuit_breaker_policy: ProviderCircuitBreakerPolicy | None = None
    max_concurrent_requests: int | None = Field(default=None, ge=1, strict=True)
    is_favorite: bool | None = None
    is_active: bool | None = None


class CreateProviderCredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1)


class UpdateProviderCredentialRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class AddCredentialPoolCredentialRequest(BaseModel):
    provider_credential_id: UUID
    priority: int = Field(default=100, ge=0)
    weight: int = Field(default=1, ge=1)
    is_active: bool = True


class UpdateCredentialPoolCredentialRequest(BaseModel):
    priority: int | None = Field(default=None, ge=0)
    weight: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class ProviderCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    created_by: UUID | None
    name: str
    key_prefix: str
    secret_backend: str = "local"
    secret_reference: str
    health_status: str
    last_validation_error: str | None
    last_validation_at: datetime | None
    last_successful_request_at: datetime | None
    last_failure_at: datetime | None
    failure_reason: str | None
    failure_message: str | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreateCredentialPoolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    selection_policy: ProviderCredentialRoutingPolicy = ProviderCredentialRoutingPolicy.priority


class UpdateCredentialPoolRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    selection_policy: ProviderCredentialRoutingPolicy | None = None
    is_active: bool | None = None


class CredentialPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    name: str
    description: str | None
    selection_policy: str
    is_active: bool
    credential_count: int = 0
    active_credential_count: int = 0
    created_at: datetime
    updated_at: datetime


class CredentialPoolCredentialResponse(BaseModel):
    id: UUID
    org_id: UUID
    pool_id: UUID
    provider_credential_id: UUID
    priority: int
    weight: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    credential: ProviderCredentialResponse


class ProviderCredentialSummary(BaseModel):
    total: int = 0
    active: int = 0
    valid: int = 0
    degraded: int = 0
    invalid: int = 0
    unchecked: int = 0


class ProviderReadiness(BaseModel):
    status: str = "needs_credential"
    message: str = "Add an active credential."
    has_active_provider: bool = False
    has_active_credential: bool = False
    has_active_pool: bool = False
    has_active_pool_credential: bool = False
    has_active_model: bool = False
    active_model_count: int = 0
    is_ready: bool = False


class ProviderOperationalState(BaseModel):
    circuit_breaker_enabled: bool = False
    circuit_state: str = "closed"
    circuit_open_until: datetime | None = None
    recent_circuit_failures: int = 0
    recent_circuit_successes: int = 0


class TestProviderCredentialResponse(BaseModel):
    id: UUID
    health_status: str
    last_validation_error: str | None = None
    last_validation_at: datetime | None = None
    last_successful_request_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_reason: str | None = None
    failure_message: str | None = None


class TestModelOfferingRequest(BaseModel):
    provider_credential_id: UUID | None = None
    credential_pool_id: UUID | None = None


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


class ModelSyncSummary(BaseModel):
    added: int = 0
    updated: int = 0
    reactivated: int = 0
    disabled: int = 0
    unchanged: int = 0
    failed: int = 0


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
    catalog_input_price_per_million_tokens: int | None
    catalog_output_price_per_million_tokens: int | None
    catalog_cached_input_price_per_million_tokens: int | None
    effective_input_price_per_million_tokens: int | None
    effective_output_price_per_million_tokens: int | None
    effective_cached_input_price_per_million_tokens: int | None
    pricing_source: str
    pricing_catalog_version: str | None
    pricing_last_refreshed_at: datetime | None
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


class SyncModelOfferingsResponse(BaseModel):
    synced_at: datetime
    status: str
    error_message: str | None = None
    summary: ModelSyncSummary = Field(default_factory=ModelSyncSummary)
    models: list[ModelOfferingResponse] = Field(default_factory=list)


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
    integration_capabilities: dict[str, bool] = Field(default_factory=dict)
    supported_integration: str
    catalog_type: str = "custom"
    request_timeout_seconds: int | None
    max_body_bytes: int | None
    retry_policy: dict[str, Any] | None
    model_sync_mode: str | None
    circuit_breaker_policy: dict[str, Any]
    max_concurrent_requests: int | None
    credential_summary: ProviderCredentialSummary = Field(default_factory=ProviderCredentialSummary)
    readiness: ProviderReadiness = Field(default_factory=ProviderReadiness)
    operational_state: ProviderOperationalState = Field(default_factory=ProviderOperationalState)
    is_favorite: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProviderImpactPolicy(BaseModel):
    id: UUID
    name: str
    route_id: UUID


class ProviderImpactResponse(BaseModel):
    access_policies: list[ProviderImpactPolicy] = Field(default_factory=list)
    active_limit_rule_count: int = 0
    active_pool_count: int = 0
    active_model_count: int = 0
    recent_usage_window_days: int = 30
    recent_request_count: int = 0
    recent_cost_cents: int = 0


class ProviderResourceImpactResponse(BaseModel):
    active_pool_membership_count: int = 0
    access_policies: list[ProviderImpactPolicy] = Field(default_factory=list)
    active_limit_rule_count: int = 0
    recent_usage_window_days: int = 30
    recent_request_count: int = 0
    recent_cost_cents: int = 0
    leaves_provider_unroutable: bool = False


class ProviderChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    messages: list[dict[str, Any]] = Field(min_length=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ProviderChatCompletionResponse(BaseModel):
    status_code: int
    body: dict[str, Any]
    provider_credential_id: UUID | None = None


class ProviderAnthropicMessagesRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    messages: list[dict[str, Any]] = Field(min_length=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ProviderAnthropicMessagesResponse(BaseModel):
    status_code: int
    body: dict[str, Any]
    provider_credential_id: UUID | None = None


class ProviderChatCompletionStream:
    def __init__(
        self,
        *,
        status_code: int,
        chunks: AsyncIterator[bytes],
        close: Callable[[], Awaitable[None]],
        media_type: str,
        provider_credential_id: UUID | None = None,
    ) -> None:
        self.status_code = status_code
        self.chunks = chunks
        self.close = close
        self.media_type = media_type
        self.provider_credential_id = provider_credential_id
