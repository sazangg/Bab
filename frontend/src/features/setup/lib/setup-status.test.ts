import { describe, expect, it } from "vitest";

import { buildSetupStatus, type SetupStatusInput } from "@/features/setup/lib/setup-status";

const emptyInput: SetupStatusInput = {
  providersCount: 0,
  readyProvidersCount: 0,
  teamsCount: 0,
  projectsCount: 0,
  usableVirtualKeysCount: 0,
  gatewayRequestsCount: 0,
  accessPoliciesCount: 0,
  limitPoliciesCount: 0,
  guardrailPoliciesCount: 0,
};

describe("buildSetupStatus", () => {
  it("returns stable ordered setup steps", () => {
    expect(buildSetupStatus(emptyInput).steps.map((step) => step.id)).toEqual([
      "provider",
      "provider_ready",
      "team",
      "project",
      "virtual_key",
      "first_request",
      "policies",
    ]);
  });

  it("reports the first incomplete required step", () => {
    const status = buildSetupStatus({
      ...emptyInput,
      providersCount: 1,
      readyProvidersCount: 1,
      teamsCount: 1,
    });

    expect(status.completedRequiredCount).toBe(3);
    expect(status.totalRequiredCount).toBe(6);
    expect(status.nextRequiredStep?.id).toBe("project");
    expect(status.isComplete).toBe(false);
  });

  it("marks setup complete when required request chain is complete", () => {
    const status = buildSetupStatus({
      ...emptyInput,
      providersCount: 1,
      readyProvidersCount: 1,
      teamsCount: 1,
      projectsCount: 1,
      usableVirtualKeysCount: 1,
      gatewayRequestsCount: 1,
    });

    expect(status.completedRequiredCount).toBe(6);
    expect(status.nextRequiredStep).toBeNull();
    expect(status.isComplete).toBe(true);
  });

  it("treats policy and guardrail configuration as optional", () => {
    const status = buildSetupStatus({
      ...emptyInput,
      guardrailPoliciesCount: 1,
    });

    expect(status.steps.find((step) => step.id === "policies")).toMatchObject({
      complete: true,
      optional: true,
    });
    expect(status.completedRequiredCount).toBe(0);
  });
});
