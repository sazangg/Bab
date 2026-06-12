import { describe, expect, it } from "vitest";

import { workspaceLandingPath } from "@/features/auth/lib/permissions";
import type { AuthenticatedUser } from "@/shared/api/generated/schemas";

function user(overrides: Partial<AuthenticatedUser>): AuthenticatedUser {
  return {
    id: crypto.randomUUID(),
    org_id: crypto.randomUUID(),
    team_id: null,
    email: "member@example.com",
    role: "org_member",
    permissions: [],
    team_memberships: [],
    project_memberships: [],
    ...overrides,
  };
}

describe("workspaceLandingPath", () => {
  it("routes direct team members to teams", () => {
    expect(
      workspaceLandingPath(
        user({
          team_memberships: [{ team_id: crypto.randomUUID(), role: "team_member" }],
        }),
      ),
    ).toBe("/teams");
  });

  it("routes project administrators to projects", () => {
    expect(
      workspaceLandingPath(
        user({
          project_memberships: [{ project_id: crypto.randomUUID(), role: "project_admin" }],
        }),
      ),
    ).toBe("/projects");
  });

  it("routes project members to projects", () => {
    expect(
      workspaceLandingPath(
        user({
          project_memberships: [{ project_id: crypto.randomUUID(), role: "project_member" }],
        }),
      ),
    ).toBe("/projects");
  });

  it("returns no landing path for an unscoped organization member", () => {
    expect(workspaceLandingPath(user({}))).toBeNull();
  });
});
