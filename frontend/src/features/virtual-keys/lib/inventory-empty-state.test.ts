import { describe, expect, it } from "vitest";

import { virtualKeyInventoryEmptyState } from "@/features/virtual-keys/lib/inventory-empty-state";

describe("virtualKeyInventoryEmptyState", () => {
  it("shows a clear-filters state when filters hide all keys", () => {
    expect(
      virtualKeyInventoryEmptyState({
        hasActiveFilters: true,
        canManageKeys: true,
        canViewSetup: true,
      }),
    ).toEqual({
      title: "No keys match",
      description: "No virtual keys match the current search or filters.",
      showClearFilters: true,
      showOpenProjects: false,
      showOpenSetup: false,
    });
  });

  it("points key managers to project-owned creation when no keys exist", () => {
    expect(
      virtualKeyInventoryEmptyState({
        hasActiveFilters: false,
        canManageKeys: true,
        canViewSetup: false,
      }),
    ).toMatchObject({
      title: "No virtual keys yet",
      showOpenProjects: true,
      showOpenSetup: false,
    });
  });

  it("also points organization admins to setup guidance", () => {
    expect(
      virtualKeyInventoryEmptyState({
        hasActiveFilters: false,
        canManageKeys: true,
        canViewSetup: true,
      }),
    ).toMatchObject({
      showOpenProjects: true,
      showOpenSetup: true,
    });
  });
});
