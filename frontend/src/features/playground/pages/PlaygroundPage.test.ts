import { describe, expect, it } from "vitest";

import { validateMaxTokens, validateTemperature } from "@/features/playground/lib/validation";

describe("Playground validation", () => {
  it("accepts valid generation controls", () => {
    expect(validateTemperature("0.2", "chat")).toBeNull();
    expect(validateMaxTokens("64", "chat")).toBeNull();
  });

  it("rejects out-of-range and non-integer controls", () => {
    expect(validateTemperature("2.1", "chat")).toBe("Temperature must be between 0 and 2.");
    expect(validateMaxTokens("1.5", "chat")).toBe("Max tokens must be a positive integer.");
  });

  it("does not validate generation controls for embeddings", () => {
    expect(validateTemperature("", "embeddings")).toBeNull();
    expect(validateMaxTokens("", "embeddings")).toBeNull();
  });
});
