import { describe, expect, it } from "vitest";

import type {
  AccessPolicyPublicModelInput,
  AccessPolicyResponse,
  LimitPolicyResponse,
} from "@/shared/api/generated/schemas";
import {
  buildAccessCreateSimulationDraft,
  buildAccessEditSimulationDraft,
  buildLimitEditSimulationDraft,
  buildLimitRuleAddSimulationDraft,
  buildLimitRuleDeleteSimulationDraft,
  buildLimitRuleEditSimulationDraft,
} from "./policySimulationDraftBuilders";

const now = "2026-01-01T00:00:00Z";

describe("policy simulation draft builders", () => {
  const publicModels: AccessPolicyPublicModelInput[] = [
    {
      public_model_name: "gpt-public",
      routing_mode: "single_route",
      fallback_on: [],
      max_route_attempts: 1,
      is_active: true,
      candidates: [
        {
          provider_id: "provider-1",
          credential_pool_id: "pool-1",
          model_offering_id: "offering-1",
          priority: 1,
          weight: 1,
          is_active: true,
        },
      ],
    },
  ];

  it("builds access edit preview as replace_policy with existing_policy_id", () => {
    const policy = accessPolicy("access-1");

    const draft = buildAccessEditSimulationDraft(policy, {
      name: " Edited access ",
      description: " updated ",
      isActive: false,
      publicModels,
    });

    expect(draft).toMatchObject({
      kind: "access",
      operation: "replace_policy",
      existing_policy_id: "access-1",
      access_policy: {
        name: "Edited access",
        description: "updated",
        public_models: publicModels,
        is_active: false,
      },
    });
    expect(draft).not.toHaveProperty("assignment");
  });

  it("builds limit edit preview as replace_policy with existing_policy_id", () => {
    const policy = limitPolicy("limit-1");

    const draft = buildLimitEditSimulationDraft(policy, {
      name: " Edited limit ",
      description: "",
      isActive: true,
    });

    expect(draft).toMatchObject({
      kind: "limit",
      operation: "replace_policy",
      existing_policy_id: "limit-1",
      limit_policy: {
        name: "Edited limit",
        description: null,
        is_active: true,
        rules: [
          {
            name: "Requests",
            limit_type: "requests",
            limit_value: 10,
            interval_unit: "day",
            interval_count: 1,
            matchers: [{ dimension: "request.endpoint", operator: "eq", value_json: "chat" }],
            partitions: [{ dimension: "virtual_key", position: 0 }],
            is_active: true,
          },
        ],
      },
    });
    expect(draft).not.toHaveProperty("assignment");
  });

  it("builds access create preview as add_policy", () => {
    const draft = buildAccessCreateSimulationDraft({
      name: " New access ",
      description: "",
      publicModels,
      assignment: { scope_type: "project", team_id: null, project_id: "project-1", virtual_key_id: null },
    });

    expect(draft).toMatchObject({
      kind: "access",
      operation: "add_policy",
      assignment: { scope_type: "project", project_id: "project-1" },
      access_policy: {
        name: "New access",
        description: null,
        public_models: publicModels,
        is_active: true,
      },
    });
    expect(draft).not.toHaveProperty("existing_policy_id");
  });

  it("builds limit rule add preview by appending the rule", () => {
    const policy = limitPolicy("limit-1");
    const draft = buildLimitRuleAddSimulationDraft(policy, {
      name: "Tokens",
      limit_type: "total_tokens",
      limit_value: 1000,
      interval_unit: "day",
      interval_count: 1,
      is_active: true,
    });

    expect(draft.kind).toBe("limit");
    expect(draft.operation).toBe("replace_policy");
    expect(draft.existing_policy_id).toBe("limit-1");
    expect(draft).not.toHaveProperty("assignment");
    expect(draft.limit_policy?.rules?.map((rule) => rule.name)).toEqual(["Requests", "Tokens"]);
  });

  it("builds limit rule edit preview by replacing only that rule", () => {
    const policy = limitPolicy("limit-1");
    const draft = buildLimitRuleEditSimulationDraft(policy, "rule-1", {
      name: "Edited requests",
      limit_type: "requests",
      limit_value: 20,
      interval_unit: "hour",
      interval_count: 1,
      is_active: false,
    });

    expect(draft.kind).toBe("limit");
    expect(draft.operation).toBe("replace_policy");
    expect(draft.existing_policy_id).toBe("limit-1");
    expect(draft).not.toHaveProperty("assignment");
    expect(draft.limit_policy?.rules).toHaveLength(1);
    expect(draft.limit_policy?.rules?.[0]).toMatchObject({
      name: "Edited requests",
      limit_value: 20,
      interval_unit: "hour",
      is_active: false,
    });
  });

  it("builds limit rule delete preview by removing only that rule", () => {
    const policy = limitPolicy("limit-1");
    policy.rules = [
      ...(policy.rules ?? []),
      {
        ...policy.rules![0],
        id: "rule-2",
        name: "Tokens",
        limit_type: "total_tokens",
      },
    ];

    const draft = buildLimitRuleDeleteSimulationDraft(policy, "rule-1");

    expect(draft.kind).toBe("limit");
    expect(draft.operation).toBe("replace_policy");
    expect(draft.existing_policy_id).toBe("limit-1");
    expect(draft).not.toHaveProperty("assignment");
    expect(draft.limit_policy?.rules?.map((rule) => rule.name)).toEqual(["Tokens"]);
  });
});

function accessPolicy(id: string): AccessPolicyResponse {
  return {
    id,
    org_id: "org-1",
    policy_id: "shared-access-1",
    name: "Access",
    description: null,
    owning_scope_type: "project",
    owning_team_id: null,
    owning_project_id: "project-1",
    owning_virtual_key_id: null,
    public_models: [],
    is_active: true,
    created_at: now,
    updated_at: now,
  };
}

function limitPolicy(id: string): LimitPolicyResponse {
  return {
    id,
    org_id: "org-1",
    policy_id: "shared-limit-1",
    name: "Limit",
    description: null,
    owning_scope_type: "project",
    owning_team_id: null,
    owning_project_id: "project-1",
    owning_virtual_key_id: null,
    is_active: true,
    created_at: now,
    updated_at: now,
    rules: [
      {
        id: "rule-1",
        org_id: "org-1",
        limit_policy_id: id,
        policy_revision_id: "revision-1",
        name: "Requests",
        limit_type: "requests",
        limit_value: 10,
        interval_unit: "day",
        interval_count: 1,
        matchers: [
          {
            id: "matcher-1",
            org_id: "org-1",
            rule_id: "rule-1",
            dimension: "request.endpoint",
            operator: "eq",
            value_json: "chat",
            created_at: now,
          },
        ],
        partitions: [
          {
            id: "partition-1",
            org_id: "org-1",
            rule_id: "rule-1",
            dimension: "virtual_key",
            position: 0,
            created_at: now,
          },
        ],
        is_active: true,
        created_at: now,
        updated_at: now,
      },
    ],
  };
}
