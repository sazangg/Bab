import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LimitPolicyResponse } from "@/shared/api/generated/schemas";
import { LimitRulesSheet } from "./PoliciesPage";

const createRuleHook = vi.hoisted(() => vi.fn());
const updateRuleHook = vi.hoisted(() => vi.fn());
const deleteRuleHook = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/generated/policies/policies", () => ({
  getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet: vi.fn(),
  useCreateLimitPolicyRuleApiV1PoliciesLimitsPolicyIdRulesPost: createRuleHook,
  useUpdateLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdPatch: updateRuleHook,
  useDeleteLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdDelete: deleteRuleHook,
  useListAccessPoliciesApiV1PoliciesAccessGet: () => ({
    data: { status: 200, data: [] },
  }),
}));

vi.mock("@/shared/api/generated/providers/providers", () => ({
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet: () => ({
    data: { status: 200, data: [] },
  }),
  useListProviderModelOfferings: () => ({
    data: { status: 200, data: { items: [] } },
  }),
  useListProvidersApiV1ProvidersGet: () => ({
    data: { status: 200, data: [] },
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const now = "2026-01-01T00:00:00Z";

describe("LimitRulesSheet", () => {
  beforeEach(() => {
    createRuleHook.mockReturnValue({ mutate: vi.fn(), isPending: false });
    updateRuleHook.mockReturnValue({ mutate: vi.fn(), isPending: false });
    deleteRuleHook.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it("passes a replace_policy draft to onPreview when previewing a rule add", async () => {
    const user = userEvent.setup();
    const onPreview = vi.fn();

    render(
      <QueryClientProvider client={new QueryClient()}>
      <LimitRulesSheet
        state={{ policy: limitPolicy() }}
        onOpenChange={vi.fn()}
        onChanged={vi.fn()}
        onPreview={onPreview}
      />
      </QueryClientProvider>,
    );

    const valueInput = screen.getAllByRole("spinbutton")[1];
    await user.clear(valueInput);
    await user.type(valueInput, "25");
    await user.click(screen.getByRole("button", { name: "Preview" }));

    expect(onPreview).toHaveBeenCalledWith([
      expect.objectContaining({
        kind: "limit",
        operation: "replace_policy",
        existing_policy_id: "limit-1",
        limit_policy: expect.objectContaining({
          rules: expect.arrayContaining([expect.objectContaining({ name: "Rule" })]),
        }),
      }),
    ]);
  });
});

function limitPolicy(): LimitPolicyResponse {
  return {
    id: "limit-1",
    org_id: "org-1",
    policy_id: "shared-limit-1",
    name: "Limit",
    description: null,
    owning_scope_type: "project",
    owning_team_id: null,
    owning_project_id: "project-1",
    owning_virtual_key_id: null,
    rules: [
      {
        id: "rule-1",
        org_id: "org-1",
        limit_policy_id: "limit-1",
        policy_revision_id: "revision-1",
        name: "Requests",
        limit_type: "requests",
        limit_value: 10,
        interval_unit: "day",
        interval_count: 1,
        provider_id: null,
        credential_pool_id: null,
        model_offering_id: null,
        access_policy_id: null,
        matchers: [],
        partitions: [],
        is_active: true,
        created_at: now,
        updated_at: now,
      },
    ],
    is_active: true,
    created_at: now,
    updated_at: now,
  };
}
