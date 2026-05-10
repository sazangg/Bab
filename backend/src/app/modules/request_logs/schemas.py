from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecordRequestLog(BaseModel):
    org_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    requested_model: str = Field(max_length=255)
    provider_model: str = Field(max_length=255)
    http_status: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str = Field(default="unknown", max_length=50)
    error_code: str | None = Field(default=None, max_length=100)


class RequestLogFilters(BaseModel):
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    provider_id: UUID | None = None
    status_code: int | None = None
    requested_model: str | None = Field(default=None, max_length=255)
    provider_model: str | None = Field(default=None, max_length=255)


class RequestLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    requested_model: str
    provider_model: str
    http_status: int
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_source: str
    error_code: str | None
    created_at: datetime
