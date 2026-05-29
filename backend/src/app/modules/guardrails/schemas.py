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


class GuardrailRuleInput(BaseModel):
    rule_type: str = Field(pattern=GUARDRAIL_RULE_TYPE_PATTERN)
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
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


class GuardrailRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID
    rule_type: str
    effect: str
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


class CreateGuardrailAssignmentRequest(BaseModel):
    policy_id: UUID
    scope_type: str = Field(pattern="^(org|team|project|allocation|virtual_key)$")
    team_id: UUID | None = None
    project_id: UUID | None = None
    allocation_id: UUID | None = None
    virtual_key_id: UUID | None = None
    enforcement_mode: str = Field(default="enforce", pattern="^(enforce|dry_run)$")
    is_active: bool = True

    @model_validator(mode="after")
    def validate_scope(self):
        expected = {
            "org": None,
            "team": self.team_id,
            "project": self.project_id,
            "allocation": self.allocation_id,
            "virtual_key": self.virtual_key_id,
        }[self.scope_type]
        if self.scope_type != "org" and expected is None:
            raise ValueError(f"{self.scope_type}_id is required")
        return self


class UpdateGuardrailAssignmentRequest(BaseModel):
    policy_id: UUID | None = None
    scope_type: str | None = Field(
        default=None,
        pattern="^(org|team|project|allocation|virtual_key)$",
    )
    team_id: UUID | None = None
    project_id: UUID | None = None
    allocation_id: UUID | None = None
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
            "allocation": self.allocation_id,
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
    allocation_id: UUID | None
    virtual_key_id: UUID | None
    enforcement_mode: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GuardrailEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    policy_id: UUID | None
    rule_id: UUID | None
    decision: str
    reason: str
    team_id: UUID | None
    project_id: UUID | None
    allocation_id: UUID | None
    virtual_key_id: UUID | None
    provider_id: UUID | None
    pool_id: UUID | None
    requested_model: str | None
    provider_model: str | None
    metadata: dict
    created_at: datetime


class GuardrailEvaluationContext(BaseModel):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    allocation_id: UUID
    allocation_chain_ids: list[UUID]
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    requested_model: str
    provider_model: str
    prompt_text: str = ""


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
