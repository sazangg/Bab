from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecordUsage(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    allocation_id: UUID
    virtual_key_id: UUID
    pool_id: UUID
    provider_id: UUID
    provider_credential_id: UUID | None
    requested_model: str
    provider_model: str
    http_status: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_cents: int | None = None
    usage_source: str = "unknown"
    error_code: str | None = None


class UsageRecordResponse(RecordUsage):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class UsageSummaryTotals(BaseModel):
    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cents: int = 0
    average_latency_ms: int | None = None


class UsageTimeSeriesPoint(UsageSummaryTotals):
    bucket: datetime


class UsageBreakdownRow(UsageSummaryTotals):
    id: str
    label: str


class AllocationUsageSummary(BaseModel):
    allocation_id: UUID
    window: str
    totals: UsageSummaryTotals
    by_virtual_key: list[UsageBreakdownRow]
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_pool: list[UsageBreakdownRow]


class VirtualKeyUsageSummary(BaseModel):
    virtual_key_id: UUID
    totals: UsageSummaryTotals
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_pool: list[UsageBreakdownRow]
    by_allocation: list[UsageBreakdownRow]


class OrganizationUsageSummary(BaseModel):
    window: str
    totals: UsageSummaryTotals
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_pool: list[UsageBreakdownRow]
    by_team: list[UsageBreakdownRow]
    by_project: list[UsageBreakdownRow]
    by_allocation: list[UsageBreakdownRow]
    by_virtual_key: list[UsageBreakdownRow]
