export type VirtualKeyInventoryEmptyState = {
  title: string;
  description: string;
  showClearFilters: boolean;
  showOpenProjects: boolean;
  showOpenSetup: boolean;
};

export function virtualKeyInventoryEmptyState({
  hasActiveFilters,
  canManageKeys,
  canViewSetup,
}: {
  hasActiveFilters: boolean;
  canManageKeys: boolean;
  canViewSetup: boolean;
}): VirtualKeyInventoryEmptyState {
  if (hasActiveFilters) {
    return {
      title: "No keys match",
      description: "No virtual keys match the current search or filters.",
      showClearFilters: true,
      showOpenProjects: false,
      showOpenSetup: false,
    };
  }

  return {
    title: "No virtual keys yet",
    description:
      "Virtual keys are created from project details after a project has effective access.",
    showClearFilters: false,
    showOpenProjects: canManageKeys,
    showOpenSetup: canManageKeys && canViewSetup,
  };
}
