import { describe, expect, it } from "vitest";

import {
  formatLimitInterval,
  limitRuleIntervalDefaults,
  policyMetadata,
  toLimitRuleInput,
} from "./policy-metadata";

describe("policyMetadata", () => {
  it("keeps stable fallbacks while metadata is unavailable", () => {
    const metadata = policyMetadata();
    expect(metadata.limitTypes).toContain("requests");
    expect(metadata.defaultIntervalUnit).toBe("day");
    expect(metadata.defaultIntervalCount).toBe(1);
  });

  it("uses backend-owned options and defaults", () => {
    const metadata = policyMetadata({
      routing_modes: ["single_route"],
      default_routing_mode: "single_route",
      fallback_reasons: [],
      default_route_priority: 7,
      default_route_weight: 3,
      limit_types: ["requests"],
      interval_units: ["hour"],
      default_interval_unit: "hour",
      default_interval_count: 2,
    });
    expect(metadata.limitTypes).toEqual(["requests"]);
    expect(metadata.intervalUnits).toEqual(["hour"]);
    expect(metadata.defaultIntervalUnit).toBe("hour");
    expect(limitRuleIntervalDefaults({
      routing_modes: ["single_route"],
      default_routing_mode: "single_route",
      fallback_reasons: [],
      default_route_priority: 7,
      default_route_weight: 3,
      limit_types: ["requests"],
      interval_units: ["month"],
      default_interval_unit: "month",
      default_interval_count: 1,
    })).toEqual({ intervalUnit: "month", intervalCount: "1" });
  });
});

describe("limit rule helpers", () => {
  it("preserves the submitted payload and lifetime interval behavior", () => {
    expect(
      toLimitRuleInput({
        name: "Budget",
        limitType: "budget_cents",
        limitValue: "12.50",
        intervalUnit: "lifetime",
        intervalCount: "9",
      }),
    ).toMatchObject({ limit_value: 1250, interval_count: 1, is_active: true });
    expect(formatLimitInterval("hour", 2)).toBe("every 2 hours");
  });
});
