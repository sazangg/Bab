export type KeyOperationalStatus = {
  label: string;
  category: "credential" | "ownership" | "routing";
  categoryLabel: string;
  reason: string;
  variant: "active" | "expired" | "revoked" | "inactive";
};

const KEY_STATUS: Record<string, KeyOperationalStatus> = {
  active: {
    label: "Active",
    category: "credential",
    categoryLabel: "Credential lifecycle",
    reason: "The credential is active and routing is ready.",
    variant: "active",
  },
  unused: {
    label: "Active, unused",
    category: "credential",
    categoryLabel: "Credential lifecycle",
    reason: "The credential is active but has not handled a request yet.",
    variant: "active",
  },
  expiring_soon: {
    label: "Expiring soon",
    category: "credential",
    categoryLabel: "Credential lifecycle",
    reason: "The credential will expire within seven days.",
    variant: "expired",
  },
  expired: {
    label: "Expired",
    category: "credential",
    categoryLabel: "Credential lifecycle",
    reason: "The credential has passed its expiration time.",
    variant: "expired",
  },
  revoked: {
    label: "Revoked",
    category: "credential",
    categoryLabel: "Credential lifecycle",
    reason: "The credential was permanently revoked.",
    variant: "revoked",
  },
  project_archived: {
    label: "Blocked by archived project",
    category: "ownership",
    categoryLabel: "Ownership lifecycle",
    reason: "The owning project is archived.",
    variant: "inactive",
  },
  team_archived: {
    label: "Blocked by archived team",
    category: "ownership",
    categoryLabel: "Ownership lifecycle",
    reason: "The owning team is archived.",
    variant: "inactive",
  },
  no_effective_access: {
    label: "No effective access",
    category: "routing",
    categoryLabel: "Routing readiness",
    reason: "No effective access route is available for this key.",
    variant: "inactive",
  },
};

export function keyStatusPresentation(status: string): KeyOperationalStatus {
  return (
    KEY_STATUS[status] ?? {
      label: "Unavailable",
      category: "routing",
      categoryLabel: "Routing readiness",
      reason: "The key is not currently usable.",
      variant: "inactive",
    }
  );
}
