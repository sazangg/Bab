import { describe, expect, it } from "vitest";

import { isWithinBcryptByteLimit } from "@/features/auth/lib/password";

describe("isWithinBcryptByteLimit", () => {
  it("measures UTF-8 bytes instead of characters", () => {
    expect(isWithinBcryptByteLimit("é".repeat(36))).toBe(true);
    expect(isWithinBcryptByteLimit("é".repeat(37))).toBe(false);
  });
});
