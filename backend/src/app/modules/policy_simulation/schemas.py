from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.guardrails.schemas import CreateGuardrailPolicyRequest
from app.modules.policies.schemas import CreateAccessPolicyRequest, CreateLimitPolicyRequest


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
