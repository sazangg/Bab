import { describe, expect, it } from "vitest";

import { scopedGrantError } from "./UsersPage";

describe("scopedGrantError", () => {
  it("requires a team role for a team-only grant", () => {
    expect(scopedGrantError("team-1", "__none__", "__none__", "__none__")).toBe(
      "Choose a team role before submitting.",
    );
  });

  it("requires a project role and permits a parent team without team membership", () => {
    expect(scopedGrantError("team-1", "__none__", "project-1", "__none__")).toBe(
      "Choose a project role before submitting.",
    );
    expect(scopedGrantError("team-1", "__none__", "project-1", "project_admin")).toBeNull();
  });
});
