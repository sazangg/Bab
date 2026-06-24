import type {
  AccessPolicyPublicModelInput,
  AccessPolicyResponse,
  LimitPolicyResponse,
  LimitPolicyRuleInput,
  LimitPolicyRuleResponse,
  PolicySimulationDraft,
} from "@/shared/api/generated/schemas";

export function buildAccessCreateSimulationDraft({
  name,
  description,
  publicModels,
  assignment,
}: {
  name: string;
  description: string;
  publicModels: AccessPolicyPublicModelInput[];
  assignment: PolicySimulationDraft["assignment"];
}): PolicySimulationDraft {
  return {
    kind: "access",
    operation: "add_policy",
    assignment,
    access_policy: {
      name: name.trim(),
      description: description.trim() || null,
      public_models: publicModels,
      is_active: true,
    },
  };
}

export function buildAccessEditSimulationDraft(
  policy: AccessPolicyResponse,
  values: {
    name: string;
    description: string;
    isActive: boolean;
    publicModels: AccessPolicyPublicModelInput[];
  },
): PolicySimulationDraft {
  return {
    kind: "access",
    operation: "replace_policy",
    existing_policy_id: policy.id,
    access_policy: {
      name: values.name.trim(),
      description: values.description.trim() || null,
      public_models: values.publicModels,
      is_active: values.isActive,
    },
  };
}

export function buildLimitEditSimulationDraft(
  policy: LimitPolicyResponse,
  values: {
    name: string;
    description: string;
    isActive: boolean;
  },
): PolicySimulationDraft {
  return {
    kind: "limit",
    operation: "replace_policy",
    existing_policy_id: policy.id,
    limit_policy: {
      name: values.name.trim(),
      description: values.description.trim() || null,
      rules: (policy.rules ?? []).map(limitRuleResponseToInput),
      is_active: values.isActive,
    },
  };
}

export function buildLimitRuleAddSimulationDraft(
  policy: LimitPolicyResponse,
  rule: LimitPolicyRuleInput,
): PolicySimulationDraft {
  return buildLimitPolicyRuleChangeDraft(policy, [
    ...(policy.rules ?? []).map(limitRuleResponseToInput),
    rule,
  ]);
}

export function buildLimitRuleEditSimulationDraft(
  policy: LimitPolicyResponse,
  ruleId: string,
  rule: LimitPolicyRuleInput,
): PolicySimulationDraft {
  return buildLimitPolicyRuleChangeDraft(
    policy,
    (policy.rules ?? []).map((current) =>
      current.id === ruleId ? rule : limitRuleResponseToInput(current),
    ),
  );
}

export function buildLimitRuleDeleteSimulationDraft(
  policy: LimitPolicyResponse,
  ruleId: string,
): PolicySimulationDraft {
  return buildLimitPolicyRuleChangeDraft(
    policy,
    (policy.rules ?? [])
      .filter((rule) => rule.id !== ruleId)
      .map(limitRuleResponseToInput),
  );
}

function buildLimitPolicyRuleChangeDraft(
  policy: LimitPolicyResponse,
  rules: LimitPolicyRuleInput[],
): PolicySimulationDraft {
  return {
    kind: "limit",
    operation: "replace_policy",
    existing_policy_id: policy.id,
    limit_policy: {
      name: policy.name,
      description: policy.description,
      rules,
      is_active: policy.is_active,
    },
  };
}

function limitRuleResponseToInput(rule: LimitPolicyRuleResponse): LimitPolicyRuleInput {
  return {
    name: rule.name,
    limit_type: rule.limit_type,
    limit_value: rule.limit_value,
    interval_unit: rule.interval_unit,
    interval_count: rule.interval_count,
    provider_id: rule.provider_id,
    credential_pool_id: rule.credential_pool_id,
    model_offering_id: rule.model_offering_id,
    access_policy_id: rule.access_policy_id,
    matchers: (rule.matchers ?? []).map((matcher) => ({
      dimension: matcher.dimension,
      operator: matcher.operator,
      value_json: matcher.value_json,
    })),
    partitions: (rule.partitions ?? []).map((partition) => ({
      dimension: partition.dimension,
      position: partition.position,
    })),
    is_active: rule.is_active,
  };
}
