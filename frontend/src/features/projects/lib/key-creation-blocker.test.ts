import { describe, expect, it } from "vitest";

import { projectKeyCreationBlocker } from "@/features/projects/lib/key-creation-blocker";

describe("projectKeyCreationBlocker", () => {
  it("explains archived projects", () => {
    expect(
      projectKeyCreationBlocker({
        projectIsActive: false,
        secretDeliveryDisabled: false,
        effectiveAccessUsable: true,
      }),
    ).toBe("Key creation is disabled because this project is archived.");
  });

  it("explains disabled secret delivery", () => {
    expect(
      projectKeyCreationBlocker({
        projectIsActive: true,
        secretDeliveryDisabled: true,
        effectiveAccessUsable: true,
      }),
    ).toBe(
      "Key creation is disabled because plaintext secret delivery is turned off in organization settings.",
    );
  });

  it("explains unusable effective access", () => {
    expect(
      projectKeyCreationBlocker({
        projectIsActive: true,
        secretDeliveryDisabled: false,
        effectiveAccessUsable: false,
      }),
    ).toBe("Key creation is disabled until this project has usable effective access.");
  });

  it("returns no blocker when creation prerequisites are satisfied", () => {
    expect(
      projectKeyCreationBlocker({
        projectIsActive: true,
        secretDeliveryDisabled: false,
        effectiveAccessUsable: true,
      }),
    ).toBeNull();
  });
});
