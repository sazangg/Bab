import { describe, expect, it } from "vitest";

import { formatMigrationStatus, resolveGatewayStatus } from "@/app/shell/operational-status";

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
