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
    adapter_type: str = Field(default="openai_compat", max_length=100)


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    adapter_type: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class CreateProviderKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1)
    priority: int = Field(default=100, ge=0)


class UpdateProviderKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1)
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProviderKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    name: str
    key_prefix: str
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateProviderModelRequest(BaseModel):
    provider_model_name: str = Field(min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)


class UpdateProviderModelRequest(BaseModel):
    provider_model_name: str | None = Field(default=None, min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class ProviderModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    provider_id: UUID
    provider_model_name: str
    alias: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    slug: str | None
    base_url: str
    adapter_type: str
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
