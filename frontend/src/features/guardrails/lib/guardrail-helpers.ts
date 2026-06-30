import type { StatusVariant } from "@/shared/components/StatusBadge";
import type {
  GuardrailAssignmentResponse,
  GuardrailEventResponse,
  GuardrailMetadataResponse,
  GuardrailPolicyResponse,
  ProjectResponse,
  TeamResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";

export const ruleTypeOptions = ["prompt_contains", "prompt_regex", "pii"];
export const responsePhaseRuleTypes = ["prompt_contains", "prompt_regex", "pii"];
export const piiRuleValues = ["email", "phone", "credit_card"];
export const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const ruleTypeLabels: Record<string, string> = {
  prompt_contains: "Prompt keyword",
  prompt_regex: "Prompt regex",
  pii: "PII detector",
};
export const matcherDimensionOptions = [
  "provider_id",
  "credential_pool_id",
  "provider_model_offering_id",
  "public_model_id",
  "public_model_name",
  "route_candidate_id",
  "gateway_endpoint",
];
export const matcherDimensionLabels: Record<string, string> = {
  provider_id: "Provider",
  credential_pool_id: "Credential pool",
  provider_model_offering_id: "Provider model",
  public_model_id: "Public model ID",
  public_model_name: "Public model name",
  route_candidate_id: "Route candidate",
  gateway_endpoint: "Gateway endpoint",
};
export const matcherOperatorOptions = ["eq", "in", "exists", "not_exists"];
export const matcherOperatorLabels: Record<string, string> = {
  eq: "Equals",
  in: "One of",
  exists: "Exists",
  not_exists: "Missing",
};

export type ScopeType = "org" | "team" | "project" | "virtual_key";
export type EventScopeType = "all" | ScopeType;
export type ScopeOption = { id: string; label: string };
export type GuardrailPolicyOption = { id: string; name: string; is_active: boolean };
export type ScopeOptions = Record<ScopeType, ScopeOption[]>;
export type ScopedVirtualKey = VirtualKeyResponse & { project_name: string };
export type GuardrailMatcherForm = {
  id: string;
  dimension: string;
  operator: string;
  value: string;
};
export type PolicyRuleForm = {
  id: string;
  rule_type: string;
  effect: string;
  phase: string;
  values: string;
  detector: string;
  matchers: GuardrailMatcherForm[];
  priority: number;
  is_active: boolean;
};
export type PolicyFormState = {
  name: string;
  description: string;
  enforcement_mode: string;
  is_active: boolean;
  rules: PolicyRuleForm[];
};
export type AssignmentFormState = {
  policy_id: string;
  scope_type: string;
  scope_id: string;
  enforcement_mode: string;
};

export type GuardrailFormMetadata = ReturnType<typeof guardrailMetadata>;

export function guardrailMetadata(metadata?: GuardrailMetadataResponse) {
  return {
    ruleTypes: metadata?.rule_types ?? ruleTypeOptions,
    piiValues: metadata?.pii_values ?? piiRuleValues,
    phases: metadata?.phases ?? ["request", "response", "both"],
    effects: metadata?.effects ?? ["allow", "deny"],
    policyEnforcementModes: metadata?.policy_enforcement_modes ?? ["enforce", "monitor"],
    assignmentEnforcementModes:
      metadata?.assignment_enforcement_modes ?? ["enforce", "dry_run"],
    defaultRuleEffect: metadata?.default_rule_effect ?? "deny",
    defaultRulePhase: metadata?.default_rule_phase ?? "both",
    defaultRulePriority: metadata?.default_rule_priority ?? 100,
    defaultPolicyEnforcementMode: metadata?.default_policy_enforcement_mode ?? "enforce",
    defaultAssignmentEnforcementMode:
      metadata?.default_assignment_enforcement_mode ?? "enforce",
  };
}

export function newRuleForm(
  overrides: Partial<PolicyRuleForm> = {},
  metadata = guardrailMetadata(),
): PolicyRuleForm {
  return {
    id: crypto.randomUUID(),
    rule_type: metadata.ruleTypes[0] ?? "prompt_contains",
    effect: metadata.defaultRuleEffect,
    phase: metadata.defaultRulePhase,
    values: "",
    detector: "local_regex",
    matchers: [],
    priority: metadata.defaultRulePriority,
    is_active: true,
    ...overrides,
  };
}

export function newMatcherForm(
  overrides: Partial<GuardrailMatcherForm> = {},
): GuardrailMatcherForm {
  return {
    id: crypto.randomUUID(),
    dimension: "public_model_name",
    operator: "eq",
    value: "",
    ...overrides,
  };
}

export const emptyPolicyForm: PolicyFormState = {
  name: "",
  description: "",
  enforcement_mode: "enforce",
  is_active: true,
  rules: [newRuleForm()],
};

export const emptyAssignmentForm: AssignmentFormState = {
  policy_id: "",
  scope_type: "none",
  scope_id: "",
  enforcement_mode: "enforce",
};

export function newPolicyForm(metadata = guardrailMetadata()): PolicyFormState {
  return {
    ...emptyPolicyForm,
    enforcement_mode: metadata.defaultPolicyEnforcementMode,
    rules: [newRuleForm({}, metadata)],
  };
}

export function newAssignmentForm(metadata = guardrailMetadata()): AssignmentFormState {
  return {
    ...emptyAssignmentForm,
    enforcement_mode: metadata.defaultAssignmentEnforcementMode,
  };
}

export function guardrailPolicyStatus(policy: GuardrailPolicyResponse): {
  label: string;
  variant: StatusVariant;
} {
  if (!policy.is_active) return { label: "Inactive", variant: "inactive" };
  if (policy.enforcement_mode === "monitor") {
    return { label: "Monitor/Dry-run", variant: "info" };
  }
  return { label: "Blocking traffic", variant: "active" };
}

export function guardrailAssignmentStatus(assignment: GuardrailAssignmentResponse): {
  label: string;
  variant: StatusVariant;
} {
  if (!assignment.is_active) return { label: "Inactive", variant: "inactive" };
  if (assignment.enforcement_mode === "dry_run") {
    return { label: "Monitor/Dry-run", variant: "info" };
  }
  return { label: "Blocking traffic", variant: "active" };
}

export function guardrailDecisionStatus(decision: string): {
  label: string;
  variant: StatusVariant;
} {
  if (decision === "blocked") return { label: "Blocked", variant: "error" };
  if (decision === "dry_run") return { label: "Dry run", variant: "info" };
  if (decision === "allowed") return { label: "Allowed", variant: "success" };
  return { label: decision, variant: "muted" };
}

export function ruleValuePlaceholder(ruleType: string) {
  if (ruleType === "pii") return "email\nphone\ncredit_card";
  if (ruleType === "prompt_regex") return "secret|confidential";
  if (ruleType === "prompt_contains") return "internal roadmap";
  return "One value per line";
}

export function ruleEffectLabel(effect: string) {
  return effect === "allow" ? "Allowlist" : "Deny";
}

export function policyRuleSummary(policy: GuardrailPolicyResponse) {
  return policy.rules
    .map(
      (rule) =>
        `${ruleEffectLabel(rule.effect)} ${rule.phase} ${ruleTypeLabels[rule.rule_type] ?? rule.rule_type}: ${rule.values.join(", ")}`,
    )
    .join(" · ");
}

export function buildRuleConfig(rule: PolicyRuleForm) {
  if (rule.rule_type !== "pii") return {};
  return { detector: rule.detector || "local_regex" };
}

export function readRuleDetector(config: unknown) {
  if (config && typeof config === "object" && "detector" in config) {
    const detector = (config as { detector?: unknown }).detector;
    if (typeof detector === "string" && detector) return detector;
  }
  return "local_regex";
}

export function parseRuleValues(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function phaseOptionsForRuleType(
  ruleType: string,
  metadata = guardrailMetadata(),
) {
  return responsePhaseRuleTypes.includes(ruleType) ? metadata.phases : ["request"];
}

export function normalizeRulePhase(
  ruleType: string,
  phase: string,
  metadata = guardrailMetadata(),
) {
  const options = phaseOptionsForRuleType(ruleType, metadata);
  return options.includes(phase) ? phase : "request";
}

export function validateRuleForm(
  rule: PolicyRuleForm,
  index: number,
  values: string[],
  metadata = guardrailMetadata(),
) {
  const label = `Rule ${index + 1}`;
  if (values.length === 0) {
    return `${label} needs at least one value.`;
  }
  if (!phaseOptionsForRuleType(rule.rule_type, metadata).includes(rule.phase)) {
    return `${label} ${ruleTypeLabels[rule.rule_type] ?? rule.rule_type} rules only support request phase.`;
  }
  if (rule.rule_type === "prompt_regex") {
    for (const value of values) {
      try {
        new RegExp(value);
      } catch {
        return `${label} has an invalid regex: ${value}`;
      }
    }
  }
  if (rule.rule_type === "pii") {
    const unsupported = values.filter(
      (value) => !metadata.piiValues.includes(value.toLowerCase()),
    );
    if (unsupported.length > 0) {
      return `${label} supports only these PII values: ${metadata.piiValues.join(", ")}.`;
    }
  }
  for (const [matcherIndex, matcher] of rule.matchers.entries()) {
    const matcherError = validateMatcherForm(matcher, index, matcherIndex);
    if (matcherError) return matcherError;
  }
  return null;
}

export function matcherNeedsValue(operator: string) {
  return operator !== "exists" && operator !== "not_exists";
}

export function parseMatcherValue(matcher: GuardrailMatcherForm) {
  if (!matcherNeedsValue(matcher.operator)) return null;
  if (matcher.operator === "in") {
    return parseRuleValues(matcher.value);
  }
  return matcher.value.trim();
}

export function validateMatcherForm(
  matcher: GuardrailMatcherForm,
  ruleIndex: number,
  matcherIndex: number,
) {
  const label = `Rule ${ruleIndex + 1} filter ${matcherIndex + 1}`;
  if (!matcherDimensionOptions.includes(matcher.dimension)) {
    return `${label} has an unsupported dimension.`;
  }
  if (!matcherOperatorOptions.includes(matcher.operator)) {
    return `${label} has an unsupported operator.`;
  }
  if (matcherNeedsValue(matcher.operator)) {
    const value = parseMatcherValue(matcher);
    if (Array.isArray(value) ? value.length === 0 : !value) {
      return `${label} needs a value.`;
    }
  }
  return null;
}

export function buildScopeOptions({
  teams,
  projects,
  virtualKeys,
  includeOrg,
}: {
  teams: TeamResponse[];
  projects: ProjectResponse[];
  virtualKeys: ScopedVirtualKey[];
  includeOrg: boolean;
}): ScopeOptions {
  return {
    org: includeOrg ? [{ id: "org", label: "Organization" }] : [],
    team: teams.map((team) => ({ id: team.id, label: team.name })),
    project: projects.map((project) => ({ id: project.id, label: project.name })),
    virtual_key: virtualKeys.map((key) => ({
      id: key.id,
      label: `${key.name} · ${key.project_name} · ${key.key_prefix}`,
    })),
  };
}

export function assignmentScopeTypes(scopeOptions: ScopeOptions) {
  return (["org", "team", "project", "virtual_key"] as ScopeType[]).filter(
    (scopeType) => scopeOptions[scopeType].length > 0,
  );
}

export function firstAssignableScope(scopeOptions: ScopeOptions) {
  return assignmentScopeTypes(scopeOptions)[0] ?? "project";
}

export function buildScopeLabels(scopeOptions: ScopeOptions) {
  return Object.fromEntries(
    Object.values(scopeOptions)
      .flat()
      .map((option) => [option.id, option.label]),
  );
}

export function labelAssignmentScope(
  assignment: GuardrailAssignmentResponse,
  scopeLabels: Record<string, string>,
) {
  const scopeId = assignment.team_id ?? assignment.project_id ?? assignment.virtual_key_id;
  if (!scopeId) return "Organization";
  return scopeLabels[scopeId] ?? scopeId;
}

export function labelEventScope(
  event: GuardrailEventResponse,
  scopeLabels: Record<string, string>,
) {
  const scopeId = event.virtual_key_id ?? event.project_id ?? event.team_id ?? null;
  if (!scopeId) return "Organization";
  return scopeLabels[scopeId] ?? scopeId;
}

export function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}
