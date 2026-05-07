from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CreateProviderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    adapter_type: str = Field(default="openai_compat", max_length=100)


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    adapter_type: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    base_url: str
    adapter_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
