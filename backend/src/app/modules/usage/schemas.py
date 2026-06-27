from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class RecordUsage(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    access_policy_id: UUID | None = None
    access_policy_route_id: UUID | None = None
    gateway_request_id: UUID | None = None
    route_attempt_id: UUID | None = None
    public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    limit_policy_ids: list[str] | None = None
    limit_policy_rule_ids: list[str] | None = None
    limit_policy_assignment_ids: list[str] | None = None
    limit_counter_key: str | None = None
    limit_counting_unit: str = "logical_request"
    limit_window_descriptor: str | None = None
    dimension_snapshot: dict = Field(default_factory=dict)
    virtual_key_id: UUID
    pool_id: UUID
    provider_id: UUID
    provider_credential_id: UUID | None
    request_id: str | None = None
    requested_model: str
    provider_model: str
    public_model_name: str | None = None
    routing_mode: str | None = None
    routing_attempt_index: int = 0
    is_final_attempt: bool = True
    primary_route_candidate_id: UUID | None = None
    fallback_from_candidate_id: UUID | None = None
    fallback_trigger_reason: str | None = None
    attempt_failure_reason: str | None = None
    gateway_endpoint: str | None = None
    http_status: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_cents: int | None = None
    cost_micro_cents: int | None = None
    usage_source: str = "unknown"
    error_code: str | None = None


class RecordLimitPolicyCommittedUsage(BaseModel):
    org_id: UUID
    usage_record_id: UUID
    limit_policy_id: UUID
    limit_policy_revision_id: UUID
    limit_policy_rule_id: UUID
    limit_policy_assignment_id: UUID
    counter_key: str | None = None
    counting_unit: str = "logical_request"
    window_descriptor: str | None = None
    dimension_snapshot: dict = Field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_cents: int | None = None
    cost_micro_cents: int | None = None


class UsageRecordResponse(RecordUsage):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    provider_credential_name: str | None = None
    provider_credential_prefix: str | None = None

    @computed_field
    @property
    def spend_type(self) -> str:
        if self.cost_cents is None or self.usage_source in {None, "unknown"}:
            return "unknown"
        if self.usage_source == "provider_reported":
            return "confirmed"
        if self.usage_source == "estimated":
            return "estimated"
        return "unknown"

    @computed_field
    @property
    def confirmed_spend_cents(self) -> int:
        return self.cost_cents or 0 if self.spend_type == "confirmed" else 0

    @computed_field
    @property
    def estimated_spend_cents(self) -> int:
        return self.cost_cents or 0 if self.spend_type == "estimated" else 0


class RecordLimitPolicyReservation(BaseModel):
    org_id: UUID
    limit_policy_id: UUID
    limit_policy_revision_id: UUID
    limit_policy_rule_id: UUID
    limit_policy_assignment_id: UUID
    virtual_key_id: UUID
    request_id: str | None = None
    counter_key: str | None = None
    counting_unit: str = "logical_request"
    window_descriptor: str | None = None
    dimension_snapshot: dict = Field(default_factory=dict)
    reserved_prompt_tokens: int = 0
    reserved_completion_tokens: int = 0
    reserved_total_tokens: int = 0
    reserved_cost_cents: int | None = None
    reserved_cost_micro_cents: int | None = None
    expires_at: datetime


class LimitPolicyReservationSummary(BaseModel):
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cents: int = 0
    cost_micro_cents: int = 0


class UsageSummaryTotals(BaseModel):
    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cents: int = 0
    confirmed_spend_cents: int = 0
    estimated_spend_cents: int = 0
    unknown_usage_count: int = 0
    unknown_total_tokens: int = 0
    average_latency_ms: int | None = None
    last_request_at: datetime | None = None


class UsageTimeSeriesPoint(UsageSummaryTotals):
    bucket: datetime


class UsageBreakdownRow(UsageSummaryTotals):
    id: str
    label: str


class UsageFilterOptions(BaseModel):
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_team: list[UsageBreakdownRow]
    by_project: list[UsageBreakdownRow]
    by_virtual_key: list[UsageBreakdownRow]


class UsageRecentError(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    request_id: str | None = None
    http_status: int
    error_code: str | None = None
    requested_model: str
    provider_model: str
    virtual_key_id: UUID


class LimitPolicyBudgetBurnRow(BaseModel):
    limit_policy_id: UUID
    limit_policy_rule_id: UUID
    limit_policy_name: str
    rule_name: str
    interval: str
    budget_cents: int
    spent_cents: int
    remaining_cents: int
    burn_rate_pct: float


class SpendInsights(BaseModel):
    window: str
    top_spend_drivers: list[UsageBreakdownRow]
    limit_policy_budget_burn: list[LimitPolicyBudgetBurnRow]


class VirtualKeyUsageSummary(BaseModel):
    virtual_key_id: UUID
    totals: UsageSummaryTotals
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_pool: list[UsageBreakdownRow]
    by_access_policy: list[UsageBreakdownRow]
    recent_errors: list[UsageRecentError] = []


class OrganizationUsageSummary(BaseModel):
    window: str
    totals: UsageSummaryTotals
    by_provider: list[UsageBreakdownRow]
    by_model: list[UsageBreakdownRow]
    by_pool: list[UsageBreakdownRow]
    by_team: list[UsageBreakdownRow]
    by_project: list[UsageBreakdownRow]
    by_access_policy: list[UsageBreakdownRow]
    by_virtual_key: list[UsageBreakdownRow]
    recent_errors: list[UsageRecentError] = []
