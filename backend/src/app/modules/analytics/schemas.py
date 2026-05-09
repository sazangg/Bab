from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AnalyticsTotals(BaseModel):
    request_count: int
    success_count: int
    error_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    average_latency_ms: int | None


class AnalyticsRecentRequest(BaseModel):
    id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    requested_model: str
    provider_model: str
    http_status: int
    latency_ms: int
    total_tokens: int | None
    error_code: str | None
    created_at: datetime


class AnalyticsTopKey(BaseModel):
    virtual_key_id: UUID
    key_name: str
    request_count: int
    total_tokens: int


class AnalyticsTimeSeriesPoint(BaseModel):
    bucket: datetime
    request_count: int
    total_tokens: int


class AnalyticsSummaryResponse(BaseModel):
    totals: AnalyticsTotals
    recent_requests: list[AnalyticsRecentRequest]
    top_keys: list[AnalyticsTopKey]
    time_series: list[AnalyticsTimeSeriesPoint]
