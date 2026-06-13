import type { StatusVariant } from "@/shared/components/StatusBadge";
import type {
  GuardrailAssignmentResponse,
  GuardrailEventResponse,
  GuardrailPolicyResponse,
  ModelOfferingResponse,
  ProjectResponse,
  TeamResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";

export const ruleTypeOptions = [
  "model",
  "provider",
  "pool",
  "prompt_contains",
  "prompt_regex",
  "pii",
];
export const responsePhaseRuleTypes = ["prompt_contains", "prompt_regex", "pii"];
export const routingRuleTypes = ["model", "provider", "pool"];
export const piiRuleValues = ["email", "phone", "credit_card"];
export const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const ruleTypeLabels: Record<string, string> = {
  model: "Model",
  provider: "Provider",
  pool: "Pool",
  prompt_contains: "Prompt keyword",
  prompt_regex: "Prompt regex",
  pii: "PII detector",
};

export type ScopeType = "org" | "team" | "project" | "virtual_key";
export type EventScopeType = "all" | ScopeType;
export type ScopeOption = { id: string; label: string };
export type GuardrailPolicyOption = { id: string; name: string; is_active: boolean };
export type ScopeOptions = Record<ScopeType, ScopeOption[]>;
export type ScopedVirtualKey = VirtualKeyResponse & { project_name: string };
export type PolicyRuleForm = {
  id: string;
  rule_type: string;
  effect: string;
  phase: string;
  values: string;
  detector: string;
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

export function newRuleForm(overrides: Partial<PolicyRuleForm> = {}): PolicyRuleForm {
  return {
    id: crypto.randomUUID(),
    rule_type: "model",
    effect: "allow",
    phase: "request",
    values: "",
    detector: "local_regex",
    priority: 100,
    is_active: true,
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

export function uniqueModelOptions(models: ModelOfferingResponse[]) {
  return Array.from(
    new Set(
      models.flatMap((model) =>
        [model.provider_model_name, model.alias].filter(
          (value): value is string => typeof value === "string" && value.length > 0,
        ),
      ),
    ),
  ).sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
}

export function ruleValuePlaceholder(ruleType: string) {
  if (ruleType === "pii") return "email\nphone\ncredit_card";
  if (ruleType === "prompt_regex") return "secret|confidential";
  if (ruleType === "prompt_contains") return "internal roadmap";
  if (ruleType === "model") return "gpt-5-mini";
  return "One UUID per line";
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

export function phaseOptionsForRuleType(ruleType: string) {
  return responsePhaseRuleTypes.includes(ruleType)
    ? ["request", "response", "both"]
    : ["request"];
}

export function normalizeRulePhase(ruleType: string, phase: string) {
  const options = phaseOptionsForRuleType(ruleType);
  return options.includes(phase) ? phase : "request";
}

export function validateRuleForm(rule: PolicyRuleForm, index: number, values: string[]) {
  const label = `Rule ${index + 1}`;
  if (values.length === 0) {
    return `${label} needs at least one value.`;
  }
  if (!phaseOptionsForRuleType(rule.rule_type).includes(rule.phase)) {
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
    const unsupported = values.filter((value) => !piiRuleValues.includes(value.toLowerCase()));
    if (unsupported.length > 0) {
      return `${label} supports only these PII values: ${piiRuleValues.join(", ")}.`;
    }
  }
  if (routingRuleTypes.includes(rule.rule_type) && rule.rule_type !== "model") {
    const invalid = values.filter((value) => !uuidPattern.test(value));
    if (invalid.length > 0) {
      return `${label} ${ruleTypeLabels[rule.rule_type]} values must be UUIDs.`;
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
