import { describe, expect, it } from "vitest";

import {
  canManageKeys,
  canViewSetup,
  canViewGatewayHistory,
  workspaceLandingPath,
} from "@/features/auth/lib/permissions";
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

  it("routes gateway-history-only users to gateway history", () => {
    expect(
      workspaceLandingPath(
        user({
          permissions: ["gateway_history.view"],
        }),
      ),
    ).toBe("/gateway-history");
  });

  it("does not grant key management to an organization viewer", () => {
    expect(
      canManageKeys(
        user({
          role: "org_viewer",
          permissions: ["projects.view"],
        }),
      ),
    ).toBe(false);
  });

  it("grants key management to project administrators", () => {
    expect(
      canManageKeys(
        user({
          project_memberships: [{ project_id: crypto.randomUUID(), role: "project_admin" }],
        }),
      ),
    ).toBe(true);
  });
});

describe("canViewGatewayHistory", () => {
  it("allows global gateway history permission", () => {
    expect(canViewGatewayHistory(user({ permissions: ["gateway_history.view"] }))).toBe(true);
  });

  it("allows direct team membership", () => {
    expect(
      canViewGatewayHistory(
        user({
          team_memberships: [{ team_id: crypto.randomUUID(), role: "team_member" }],
        }),
      ),
    ).toBe(true);
  });

  it("allows project membership", () => {
    expect(
      canViewGatewayHistory(
        user({
          project_memberships: [{ project_id: crypto.randomUUID(), role: "project_member" }],
        }),
      ),
    ).toBe(true);
  });

  it("denies unscoped organization members", () => {
    expect(canViewGatewayHistory(user({}))).toBe(false);
  });
});

describe("canViewSetup", () => {
  it("allows organization owners and administrators", () => {
    expect(canViewSetup(user({ role: "org_owner" }))).toBe(true);
    expect(canViewSetup(user({ role: "org_admin" }))).toBe(true);
  });

  it("denies organization viewers and scoped users", () => {
    expect(canViewSetup(user({ role: "org_viewer" }))).toBe(false);
    expect(
      canViewSetup(
        user({
          team_memberships: [{ team_id: crypto.randomUUID(), role: "team_admin" }],
        }),
      ),
    ).toBe(false);
  });
});
