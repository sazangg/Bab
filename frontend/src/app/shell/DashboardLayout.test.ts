import { describe, expect, it } from "vitest";

import { visibleNavigationGroups } from "@/app/shell/navigation";
import { formatMigrationStatus, resolveGatewayStatus } from "@/app/shell/operational-status";
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

function visibleLabels(authenticatedUser: AuthenticatedUser, production = true) {
  return visibleNavigationGroups(authenticatedUser, { production }).flatMap((group) =>
    group.items.map((item) => item.label),
  );
}

describe("operational shell status", () => {
  it("distinguishes ready, degraded, and unavailable states", () => {
    expect(resolveGatewayStatus()).toMatchObject({ label: "Status unavailable" });
    expect(
      resolveGatewayStatus(503, {
        status: "not_ready",
        checks: { database: { ok: false } },
      }),
    ).toMatchObject({ label: "Gateway degraded" });
    expect(
      resolveGatewayStatus(200, {
        status: "ready",
        checks: { database: { ok: true } },
      }),
    ).toMatchObject({ label: "Gateway ready" });
  });

  it("formats migration diagnostics for administrators", () => {
    expect(formatMigrationStatus({ ok: true, current_revision: "abc" })).toBe("Current (abc)");
    expect(
      formatMigrationStatus({
        ok: false,
        current_revision: "abc",
        head_revision: "def",
      }),
    ).toBe("Behind: abc to def");
    expect(formatMigrationStatus({ ok: false, error: "DatabaseError" })).toBe(
      "Unavailable: DatabaseError",
    );
  });
});

describe("shell navigation model", () => {
  it("shows target product groups for organization administrators", () => {
    const groups = visibleNavigationGroups(
      user({
        role: "org_admin",
        permissions: [
          "teams.view",
          "projects.view",
          "keys.manage",
          "providers.view",
          "policies.view",
          "guardrails.view",
          "usage.view",
          "gateway_history.view",
          "members.manage",
          "activity.view",
          "audit.view",
          "settings.view",
        ],
      }),
      { production: true },
    );

    expect(groups.map((group) => group.label)).toEqual([
      "Overview",
      "Workspace",
      "AI Gateway",
      "Control",
      "Administration",
    ]);
    expect(groups.find((group) => group.label === "AI Gateway")?.items.map((item) => item.label))
      .toEqual(["Playground", "Gateway history", "Usage & cost", "API docs"]);
    expect(groups.find((group) => group.label === "Overview")?.items.map((item) => item.label))
      .toEqual(["Overview", "Setup"]);
  });

  it("keeps organization viewers read-only and permission-driven", () => {
    const labels = visibleLabels(
      user({
        role: "org_viewer",
        permissions: [
          "teams.view",
          "projects.view",
          "providers.view",
          "policies.view",
          "guardrails.view",
          "usage.view",
          "gateway_history.view",
          "activity.view",
          "settings.view",
        ],
      }),
    );

    expect(labels).toContain("Overview");
    expect(labels).toContain("Gateway history");
    expect(labels).toContain("Usage & cost");
    expect(labels).not.toContain("Setup");
    expect(labels).not.toContain("Virtual keys");
    expect(labels).not.toContain("Users");
    expect(labels).not.toContain("Audit");
  });

  it("limits scoped members to scoped workspace and operations surfaces", () => {
    const labels = visibleLabels(
      user({
        team_memberships: [{ team_id: crypto.randomUUID(), role: "team_member" }],
      }),
    );

    expect(labels).toEqual(["Teams", "Projects", "Gateway history", "Usage & cost", "Activity"]);
    expect(labels).not.toContain("Setup");
  });

  it("shows Gateway history for project-scoped users", () => {
    const labels = visibleLabels(
      user({
        project_memberships: [{ project_id: crypto.randomUUID(), role: "project_member" }],
      }),
    );

    expect(labels).toContain("Gateway history");
    expect(labels).not.toContain("Overview");
  });

  it("hides Gateway history for users without permission or membership", () => {
    expect(visibleLabels(user({}))).not.toContain("Gateway history");
  });

  it("hides Design system in production", () => {
    const admin = user({ role: "org_admin", permissions: ["*"] });

    expect(visibleLabels(admin, true)).not.toContain("Design system");
    expect(visibleLabels(admin, false)).toContain("Design system");
  });
});
