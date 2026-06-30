import { describe, expect, it } from "vitest";

import { getProviderReadiness, providerReadinessActionLabel } from "./provider-readiness";

const readyInput = {
  providerEnabled: true,
  credentialCount: 1,
  validatedCredentialCount: 1,
  poolCount: 1,
  poolsWithCredentialsCount: 1,
  modelCount: 1,
};

describe("provider readiness", () => {
  it("orders setup steps and returns the next missing prerequisite", () => {
    const readiness = getProviderReadiness({
      ...readyInput,
      poolCount: 0,
      poolsWithCredentialsCount: 0,
      modelCount: 0,
    });

    expect(readiness.isReady).toBe(false);
    expect(readiness.nextAction).toBe("create_pool");
    expect(readiness.steps.map((step) => step.id)).toEqual([
      "enabled",
      "credential",
      "validated_credential",
      "pool",
      "pool_credential",
      "model",
    ]);
  });

  it("points disabled providers to enabling before resource setup", () => {
    const readiness = getProviderReadiness({ ...readyInput, providerEnabled: false });

    expect(readiness.nextAction).toBe("enable_provider");
    expect(providerReadinessActionLabel(readiness.nextAction)).toBe("Enable provider");
  });

  it("detects ready providers", () => {
    const readiness = getProviderReadiness(readyInput);

    expect(readiness.isReady).toBe(true);
    expect(readiness.nextAction).toBe("open_playground");
  });

  it("points pools without credentials to pool configuration", () => {
    const readiness = getProviderReadiness({
      ...readyInput,
      poolsWithCredentialsCount: 0,
      modelCount: 0,
    });

    expect(readiness.nextAction).toBe("attach_credential");
  });
});
