import type {
  LimitPolicyRuleInput,
  PolicyMetadataResponse,
} from "@/shared/api/generated/schemas";

const fallbackLimitTypes = [
  "budget_cents",
  "requests",
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "tokens_per_request",
];
const fallbackIntervalUnits = ["minute", "hour", "day", "week", "month", "lifetime"];

const limitTypeLabels: Record<string, string> = {
  budget_cents: "Spend budget",
  requests: "Request count",
  input_tokens: "Input tokens",
  output_tokens: "Output tokens",
  total_tokens: "Total tokens",
  tokens_per_request: "Tokens per request",
};

export function policyMetadata(metadata?: PolicyMetadataResponse) {
  const limitTypes = metadata?.limit_types ?? fallbackLimitTypes;
  const intervalUnits = metadata?.interval_units ?? fallbackIntervalUnits;
  return {
    limitTypes,
    intervalUnits,
    limitTypeLabels: Object.fromEntries(
      limitTypes.map((value) => [value, limitTypeLabels[value] ?? humanize(value)]),
    ),
    intervalUnitLabels: Object.fromEntries(
      intervalUnits.map((value) => [value, humanize(value)]),
    ),
    defaultIntervalUnit: metadata?.default_interval_unit ?? "day",
    defaultIntervalCount: metadata?.default_interval_count ?? 1,
  };
}

export function limitRuleIntervalDefaults(metadata?: PolicyMetadataResponse) {
  const resolved = policyMetadata(metadata);
  return {
    intervalUnit: resolved.defaultIntervalUnit,
    intervalCount: String(resolved.defaultIntervalCount),
  };
}

export type DraftLimitRule = {
  name: string;
  limitType: string;
  limitValue: string;
  intervalUnit: string;
  intervalCount: string;
};

export function toLimitRuleInput(
  rule: DraftLimitRule,
  isActive = true,
): LimitPolicyRuleInput {
  return {
    name: rule.name,
    limit_type: rule.limitType,
    limit_value:
      rule.limitType === "budget_cents"
        ? Math.round(Number(rule.limitValue) * 100)
        : Number(rule.limitValue),
    interval_unit: rule.intervalUnit,
    interval_count: rule.intervalUnit === "lifetime" ? 1 : Number(rule.intervalCount || 1),
    is_active: isActive,
  };
}

export function formatLimitType(value: string) {
  return limitTypeLabels[value] ?? humanize(value);
}

export function formatLimitInterval(intervalUnit: string, intervalCount: string | number) {
  if (intervalUnit === "lifetime") return "over lifetime";
  const count = Number(intervalCount) || 1;
  return `every ${count} ${intervalUnit}${count === 1 ? "" : "s"}`;
}

function humanize(value: string) {
  const label = value.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}
