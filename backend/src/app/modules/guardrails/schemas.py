import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GUARDRAIL_RULE_TYPES = (
    "model",
    "provider",
    "pool",
    "prompt_contains",
    "prompt_regex",
    "pii",
)
GUARDRAIL_RULE_TYPE_PATTERN = f"^({'|'.join(GUARDRAIL_RULE_TYPES)})$"
ROUTING_RULE_TYPES = {"model", "provider", "pool"}
PII_RULE_VALUES = {"email", "phone", "credit_card"}
# Bounds on author-supplied regex rules to limit the ReDoS attack surface.
MAX_REGEX_VALUES_PER_RULE = 25
MAX_REGEX_PATTERN_LENGTH = 512


class GuardrailRuleInput(BaseModel):
    rule_type: str = Field(pattern=GUARDRAIL_RULE_TYPE_PATTERN)
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
    phase: str = Field(default="both", pattern="^(request|response|both)$")
    values: list[str] = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=1)
    is_active: bool = True

    @field_validator("values")
    @classmethod
    def strip_values(cls, value: list[str]) -> list[str]:
        values = [item.strip() for item in value if item.strip()]
        if not values:
            raise ValueError("values must contain at least one non-empty item")
        return values

    @model_validator(mode="after")
    def validate_rule_configuration(self):
        if self.phase == "response" and self.rule_type in ROUTING_RULE_TYPES:
            raise ValueError(f"{self.rule_type} rules only support request-phase evaluation")
        if self.rule_type == "prompt_regex":
            if len(self.values) > MAX_REGEX_VALUES_PER_RULE:
                raise ValueError(
                    f"at most {MAX_REGEX_VALUES_PER_RULE} regex patterns are allowed per rule"
                )
            for value in self.values:
                if len(value) > MAX_REGEX_PATTERN_LENGTH:
                    raise ValueError(f"regex pattern exceeds {MAX_REGEX_PATTERN_LENGTH} characters")
                try:
                    re.compile(value)
                except re.error as exc:
                    raise ValueError(f"invalid regex {value!r}: {exc}") from exc
        if self.rule_type == "pii":
            unsupported = sorted({value.lower() for value in self.values} - PII_RULE_VALUES)
            if unsupported:
                raise ValueError(f"unsupported PII values: {', '.join(unsupported)}")
        return self


class GuardrailRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID
    rule_type: str
    effect: str
    phase: str
    values: list[str]
    config: dict[str, Any]
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateGuardrailPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    enforcement_mode: str = Field(default="enforce", pattern="^(enforce|monitor)$")
    is_active: bool = True
    rules: list[GuardrailRuleInput] = Field(default_factory=list)


class UpdateGuardrailPolicyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    enforcement_mode: str | None = Field(default=None, pattern="^(enforce|monitor)$")
    is_active: bool | None = None
    rules: list[GuardrailRuleInput] | None = None


class GuardrailPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    enforcement_mode: str
    is_active: bool
    rules: list[GuardrailRuleResponse]
    created_at: datetime
    updated_at: datetime


class GuardrailPolicyOptionResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool


class CreateGuardrailAssignmentRequest(BaseModel):
    policy_id: UUID
    scope_type: str = Field(pattern="^(org|team|project|virtual_key)$")
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    enforcement_mode: str = Field(default="enforce", pattern="^(enforce|dry_run)$")
    is_active: bool = True

    @model_validator(mode="after")
    def validate_scope(self):
        expected = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected is None:
            raise ValueError(f"{self.scope_type}_id is required")
        return self


class UpdateGuardrailAssignmentRequest(BaseModel):
    policy_id: UUID | None = None
    scope_type: str | None = Field(
        default=None,
        pattern="^(org|team|project|virtual_key)$",
    )
    team_id: UUID | None = None
    project_id: UUID | None = None
    virtual_key_id: UUID | None = None
    enforcement_mode: str | None = Field(default=None, pattern="^(enforce|dry_run)$")
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type is None:
            return self
        expected = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected is None:
            raise ValueError(f"{self.scope_type}_id is required")
        return self


class GuardrailAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID
    policy_name: str
    scope_type: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    enforcement_mode: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GuardrailImpactTarget(BaseModel):
    id: UUID
    name: str


class GuardrailImpactVirtualKey(GuardrailImpactTarget):
    project_id: UUID
    project_name: str


class GuardrailImpactResponse(BaseModel):
    affected_teams: list[GuardrailImpactTarget] = Field(default_factory=list)
    affected_projects: list[GuardrailImpactTarget] = Field(default_factory=list)
    affected_virtual_keys: list[GuardrailImpactVirtualKey] = Field(default_factory=list)
    affected_team_count: int = 0
    affected_project_count: int = 0
    affected_virtual_key_count: int = 0
    virtual_keys_would_become_unusable: list[GuardrailImpactVirtualKey] = Field(
        default_factory=list
    )
    virtual_keys_would_become_unusable_count: int = 0


class GuardrailEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID | None
    rule_id: UUID | None
    decision: str
    phase: str
    reason: str
    team_id: UUID | None
    project_id: UUID | None
    virtual_key_id: UUID | None
    provider_id: UUID | None
    pool_id: UUID | None
    request_id: str | None
    requested_model: str | None
    provider_model: str | None
    metadata: dict
    created_at: datetime


class GuardrailEvaluationContext(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    request_id: str | None = None
    requested_model: str
    provider_model: str
    prompt_text: str = ""
    response_text: str = ""
    phase: str = Field(default="request", pattern="^(request|response)$")


class GuardrailSimulationRequest(BaseModel):
    policy_id: UUID | None = None
    rules: list[GuardrailRuleInput] | None = None
    enforcement_mode: str = Field(default="enforce", pattern="^(enforce|monitor)$")
    requested_model: str
    provider_model: str | None = None
    provider_id: UUID | None = None
    pool_id: UUID | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    prompt_text: str | None = None

    @model_validator(mode="after")
    def validate_policy_or_rules(self):
        if self.policy_id is None and not self.rules:
            raise ValueError("policy_id or rules is required")
        return self


class GuardrailSimulationMatch(BaseModel):
    rule_id: UUID | None = None
    rule_type: str
    effect: str
    priority: int
    decision: str
    reason: str
    matched_values: list[str]


class GuardrailSimulationResponse(BaseModel):
    decision: str
    enforcement_mode: str
    matches: list[GuardrailSimulationMatch]
