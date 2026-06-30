import { describe, expect, it } from "vitest";

import {
  guardrailMetadata,
  newAssignmentForm,
  newPolicyForm,
  validateRuleForm,
} from "./guardrail-helpers";

describe("guardrail metadata", () => {
  it("keeps current defaults while metadata is unavailable", () => {
    const metadata = guardrailMetadata();
    expect(metadata.ruleTypes).toContain("pii");
    expect(newPolicyForm(metadata).rules[0]).toMatchObject({
      effect: "deny",
      phase: "both",
      priority: 100,
    });
  });

  it("uses backend-owned options and defaults", () => {
    const metadata = guardrailMetadata({
      rule_types: ["pii"],
      pii_values: ["email"],
      phases: ["request"],
      effects: ["deny"],
      policy_enforcement_modes: ["monitor"],
      assignment_enforcement_modes: ["dry_run"],
      default_rule_effect: "deny",
      default_rule_phase: "request",
      default_rule_priority: 25,
      default_policy_enforcement_mode: "monitor",
      default_assignment_enforcement_mode: "dry_run",
    });
    expect(newPolicyForm(metadata)).toMatchObject({
      enforcement_mode: "monitor",
      rules: [{ rule_type: "pii", phase: "request", priority: 25 }],
    });
    expect(newAssignmentForm(metadata).enforcement_mode).toBe("dry_run");
    expect(
      validateRuleForm(newPolicyForm(metadata).rules[0], 0, ["phone"], metadata),
    ).toContain("email");
  });
});
