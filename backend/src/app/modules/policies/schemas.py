from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.guardrails.schemas import CreateGuardrailPolicyRequest


class AccessPolicyRouteCandidateInput(BaseModel):
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_id: UUID
    priority: int = Field(default=100, ge=1)
    weight: int = Field(default=100, ge=1)
    is_active: bool = True


class AccessPolicyPublicModelInput(BaseModel):
    public_model_name: str = Field(min_length=1, max_length=255)
    routing_mode: str = Field(default="single_route", pattern="^(single_route|ordered_fallback)$")
    fallback_on: list[str] = Field(default_factory=list)
    max_route_attempts: int | None = Field(default=None, ge=1)
    is_active: bool = True
    candidates: list[AccessPolicyRouteCandidateInput] = Field(min_length=1)


class CreateAccessPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    public_models: list[AccessPolicyPublicModelInput] = Field(default_factory=list)
    is_active: bool = True


class UpdateAccessPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    public_models: list[AccessPolicyPublicModelInput] | None = None


class AccessPolicyRouteCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    public_model_id: UUID
    provider_id: UUID
    credential_pool_id: UUID
    model_offering_id: UUID
    priority: int
    weight: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccessPolicyPublicModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    access_policy_id: UUID
    public_model_name: str
    routing_mode: str
    fallback_on: list[str]
    max_route_attempts: int | None
    is_active: bool
    candidates: list[AccessPolicyRouteCandidateResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AccessPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID | None
    name: str
    description: str | None
    owning_scope_type: str | None
    owning_team_id: UUID | None
    owning_project_id: UUID | None
    owning_virtual_key_id: UUID | None
    public_models: list[AccessPolicyPublicModelResponse] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccessPolicyModelOption(BaseModel):
    id: UUID
    provider_model_name: str


class AccessPolicyPoolOption(BaseModel):
    id: UUID
    name: str
    models: list[AccessPolicyModelOption] = Field(default_factory=list)


class AccessPolicyProviderOption(BaseModel):
    id: UUID
    display_name: str
    pools: list[AccessPolicyPoolOption] = Field(default_factory=list)


class AccessPolicyOptionsResponse(BaseModel):
    providers: list[AccessPolicyProviderOption] = Field(default_factory=list)


class CreateLimitPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    rules: list["LimitPolicyRuleInput"] = Field(default_factory=list)
    is_active: bool = True


class LimitPolicyRuleMatcherInput(BaseModel):
    dimension: str = Field(min_length=1, max_length=100)
    operator: str = Field(pattern="^(eq|in|exists|not_exists)$")
    value_json: Any = None


class LimitPolicyRulePartitionInput(BaseModel):
    dimension: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=0)


class LimitPolicyRuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    limit_type: str = Field(
        pattern="^(budget_cents|requests|input_tokens|output_tokens|total_tokens|tokens_per_request)$"
    )
    limit_value: int = Field(ge=1)
    interval_unit: str = Field(default="month", pattern="^(minute|hour|day|week|month|lifetime)$")
    interval_count: int = Field(default=1, ge=1)
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    matchers: list[LimitPolicyRuleMatcherInput] = Field(default_factory=list)
    partitions: list[LimitPolicyRulePartitionInput] = Field(default_factory=list)
    is_active: bool = True


class UpdateLimitPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class CreateLimitPolicyRuleRequest(LimitPolicyRuleInput):
    pass


class UpdateLimitPolicyRuleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    limit_type: str | None = Field(
        default=None,
        pattern="^(budget_cents|requests|input_tokens|output_tokens|total_tokens|tokens_per_request)$",
    )
    limit_value: int | None = Field(default=None, ge=1)
    interval_unit: str | None = Field(
        default=None, pattern="^(minute|hour|day|week|month|lifetime)$"
    )
    interval_count: int | None = Field(default=None, ge=1)
    provider_id: UUID | None = None
    credential_pool_id: UUID | None = None
    model_offering_id: UUID | None = None
    access_policy_id: UUID | None = None
    matchers: list[LimitPolicyRuleMatcherInput] | None = None
    partitions: list[LimitPolicyRulePartitionInput] | None = None
    is_active: bool | None = None


class LimitPolicyRuleMatcherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    rule_id: UUID
    dimension: str
    operator: str
    value_json: Any = None
    created_at: datetime


class LimitPolicyRulePartitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    rule_id: UUID
    dimension: str
    position: int
    created_at: datetime


class LimitPolicyRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    limit_policy_id: UUID
    policy_revision_id: UUID | None
    name: str
    limit_type: str
    limit_value: int
    interval_unit: str
    interval_count: int
    provider_id: UUID | None
    credential_pool_id: UUID | None
    model_offering_id: UUID | None
    access_policy_id: UUID | None
    matchers: list[LimitPolicyRuleMatcherResponse] = Field(default_factory=list)
    partitions: list[LimitPolicyRulePartitionResponse] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LimitPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID | None
    name: str
    description: str | None
    owning_scope_type: str | None
    owning_team_id: UUID | None
    owning_project_id: UUID | None
    owning_virtual_key_id: UUID | None
    rules: list[LimitPolicyRuleResponse] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreatePolicyAssignmentRequest(BaseModel):
    policy_id: UUID
    policy_type: str = Field(pattern="^(access|limit)$")
    scope_type: str = Field(pattern="^(org|team|project|virtual_key)$")
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_assignment(self):
        expected_scope_id = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected_scope_id is None:
            raise ValueError(f"{self.scope_type}_id is required for this scope")
        return self


class UpdatePolicyAssignmentRequest(BaseModel):
    is_active: bool | None = None


class PolicyAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID | None
    policy_type: str
    access_policy_id: UUID | None
    limit_policy_id: UUID | None
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    scope_target_key: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateScopedPolicyAssignmentRequest(BaseModel):
    policy_type: str = Field(pattern="^(access|limit)$")
    access_policy: CreateAccessPolicyRequest | None = None
    limit_policy: CreateLimitPolicyRequest | None = None
    scope_type: str = Field(pattern="^(team|project|virtual_key)$")
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_scoped_policy_assignment(self):
        if self.policy_type == "access" and self.access_policy is None:
            raise ValueError("access_policy is required for access scoped policy assignments")
        if self.policy_type == "limit" and self.limit_policy is None:
            raise ValueError("limit_policy is required for limit scoped policy assignments")
        expected_scope_id = {
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if expected_scope_id is None:
            raise ValueError(f"{self.scope_type}_id is required for this scope")
        return self


class ScopedPolicyAssignmentResponse(BaseModel):
    policy_type: str
    access_policy: AccessPolicyResponse | None = None
    limit_policy: LimitPolicyResponse | None = None
    assignment: PolicyAssignmentResponse


class PolicyImpactTarget(BaseModel):
    id: UUID
    name: str


class PolicyImpactVirtualKey(PolicyImpactTarget):
    project_id: UUID
    project_name: str


class PolicyImpactResponse(BaseModel):
    affected_teams: list[PolicyImpactTarget] = Field(default_factory=list)
    affected_projects: list[PolicyImpactTarget] = Field(default_factory=list)
    affected_virtual_keys: list[PolicyImpactVirtualKey] = Field(default_factory=list)
    affected_team_count: int = 0
    affected_project_count: int = 0
    affected_virtual_key_count: int = 0
    virtual_keys_would_become_unusable: list[PolicyImpactVirtualKey] = Field(default_factory=list)
    virtual_keys_would_become_unusable_count: int = 0


class PolicySimulationTarget(BaseModel):
    virtual_key_id: UUID


class PolicySimulationGuardrailInput(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    prompt_text: str | None = None
    response_text: str | None = None


class PolicySimulationDraftAssignment(BaseModel):
    scope_type: Literal["org", "team", "project", "virtual_key"]
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    guardrail_assignment_mode: Literal["enforce", "dry_run"] | None = None

    @model_validator(mode="after")
    def validate_assignment_scope(self):
        expected_scope_id = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected_scope_id is None:
            raise ValueError(f"{self.scope_type}_id is required for this scope")
        return self


class PolicySimulationDraft(BaseModel):
    kind: Literal["access", "limit", "guardrail"]
    operation: Literal["add_policy", "replace_policy"]
    existing_policy_id: UUID | None = None
    assignment: PolicySimulationDraftAssignment | None = None
    access_policy: CreateAccessPolicyRequest | None = None
    limit_policy: CreateLimitPolicyRequest | None = None
    guardrail_policy: CreateGuardrailPolicyRequest | None = None

    @model_validator(mode="after")
    def validate_draft(self):
        if self.operation == "replace_policy" and self.existing_policy_id is None:
            raise ValueError("existing_policy_id is required for replace_policy drafts")
        if self.operation == "add_policy" and self.assignment is None:
            raise ValueError("assignment is required for add_policy drafts")
        payloads = {
            "access": self.access_policy,
            "limit": self.limit_policy,
            "guardrail": self.guardrail_policy,
        }
        if payloads[self.kind] is None:
            raise ValueError(f"{self.kind}_policy is required for {self.kind} drafts")
        if sum(payload is not None for payload in payloads.values()) != 1:
            raise ValueError("draft kind must match exactly one policy payload")
        if (
            self.kind in {"access", "limit"}
            and self.assignment is not None
            and self.assignment.guardrail_assignment_mode is not None
        ):
            raise ValueError("guardrail_assignment_mode is only valid for guardrail drafts")
        return self


class PolicySimulationRequest(BaseModel):
    target: PolicySimulationTarget
    requested_model: str = Field(min_length=1, max_length=255)
    gateway_endpoint: Literal[
        "chat_completions",
        "responses",
        "completions",
        "anthropic_messages",
    ]
    streaming: bool = False
    provider_id: UUID | None = None
    estimated_input_tokens: int = Field(default=0, ge=0)
    requested_output_tokens: int | None = Field(default=None, ge=0)
    include_limits: bool = True
    include_guardrails: bool = True
    evaluate_all_route_candidates: bool = True
    guardrail_input: PolicySimulationGuardrailInput | None = None
    drafts: list[PolicySimulationDraft] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_drafts(self):
        replacements = set[tuple[str, UUID]]()
        for draft in self.drafts:
            if draft.operation != "replace_policy" or draft.existing_policy_id is None:
                continue
            key = (draft.kind, draft.existing_policy_id)
            if key in replacements:
                raise ValueError("duplicate draft replacement for the same policy")
            replacements.add(key)
        return self


class PolicySimulationSubject(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    virtual_key_name: str | None = None
    requested_model: str
    gateway_endpoint: str
    streaming: bool
    provider_id: UUID | None = None


class PolicySimulationRouteAttempt(BaseModel):
    candidate_index: int
    attempt_index: int | None = None
    selected: bool
    would_attempt: bool
    skipped_reason: str | None = None
    skipped_message: str | None = None
    access_policy_id: UUID | None = None
    access_policy_revision_id: UUID | None = None
    access_policy_assignment_id: UUID | None = None
    public_model_id: UUID | None = None
    route_candidate_id: UUID | None = None
    public_model_name: str | None = None
    routing_mode: str | None = None
    provider_id: UUID | None = None
    provider_name: str | None = None
    credential_pool_id: UUID | None = None
    credential_pool_name: str | None = None
    provider_model_offering_id: UUID | None = None
    provider_model: str | None = None
    input_price_per_million_tokens: int | None = None
    output_price_per_million_tokens: int | None = None
    draft_ref: str | None = None


class PolicySimulationDecision(BaseModel):
    decision_type: Literal[
        "access",
        "limit",
        "guardrail",
        "provider_routing",
        "request_validation",
    ]
    stage: str
    outcome: Literal[
        "allowed",
        "denied",
        "would_allow",
        "would_deny",
        "matched",
        "not_matched",
        "selected",
        "skipped",
    ]
    effective_action: Literal["allow", "deny", "would_allow", "would_deny"] | None = None
    enforced: bool
    policy_id: UUID | None = None
    policy_name: str | None = None
    policy_kind: str | None = None
    policy_revision_id: UUID | None = None
    policy_revision_number: int | None = None
    assignment_id: UUID | None = None
    assignment_mode: str | None = None
    assignment_scope_type: str | None = None
    assignment_scope_label: str | None = None
    rule_id: UUID | None = None
    rule_name: str | None = None
    route_candidate_id: UUID | None = None
    reason_code: str | None = None
    message: str | None = None
    dimension_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    draft_ref: str | None = None


class PolicySimulationLimitResult(BaseModel):
    route_candidate_id: UUID | None = None
    policy_id: UUID | None = None
    policy_name: str | None = None
    policy_revision_id: UUID | None = None
    policy_revision_number: int | None = None
    rule_id: UUID | None = None
    rule_name: str | None = None
    assignment_id: UUID | None = None
    assignment_mode: str | None = None
    assignment_scope_label: str | None = None
    limit_type: str
    limit_value: int
    interval_unit: str
    interval_count: int
    counter_key: str | None = None
    counting_unit: Literal["logical_request", "route_attempt"]
    window_descriptor: str | None = None
    current_usage: int | None = None
    active_reserved_usage: int | None = None
    attempted_usage: int | None = None
    would_deny: bool
    reason_code: str | None = None
    message: str | None = None
    draft_ref: str | None = None


class PolicySimulationGuardrailResult(BaseModel):
    route_candidate_id: UUID | None = None
    policy_id: UUID | None = None
    policy_name: str | None = None
    policy_revision_id: UUID | None = None
    policy_revision_number: int | None = None
    rule_id: UUID | None = None
    rule_name: str | None = None
    assignment_id: UUID | None = None
    assignment_mode: str | None = None
    assignment_scope_label: str | None = None
    phase: Literal["request", "response"]
    rule_type: str
    effect: Literal["allow", "deny"]
    applicability_matched: bool
    detector_evaluated: bool
    matched_values: list[str] = Field(default_factory=list)
    decision: Literal["allowed", "blocked", "would_block", "not_evaluated", "not_applicable"]
    reason_code: str | None = None
    message: str | None = None
    draft_ref: str | None = None


class PolicySimulationWarning(BaseModel):
    code: str
    message: str
    route_candidate_id: UUID | None = None
    policy_id: UUID | None = None
    rule_id: UUID | None = None
    draft_ref: str | None = None


class PolicySimulationResponse(BaseModel):
    subject: PolicySimulationSubject
    final_decision: Literal["allow", "deny", "would_deny"]
    denied_stage: str | None = None
    denied_reason: str | None = None
    requested_model: str
    public_model_name: str | None = None
    routing_mode: str | None = None
    fallback_on: list[str] = Field(default_factory=list)
    provider_pinned: bool = False
    fallback_disabled_reason: str | None = None
    route_attempts: list[PolicySimulationRouteAttempt] = Field(default_factory=list)
    decisions: list[PolicySimulationDecision] = Field(default_factory=list)
    limit_results: list[PolicySimulationLimitResult] = Field(default_factory=list)
    guardrail_results: list[PolicySimulationGuardrailResult] = Field(default_factory=list)
    warnings: list[PolicySimulationWarning] = Field(default_factory=list)
