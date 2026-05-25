import type { AuthenticatedUser } from "@/shared/api/generated/schemas";

export function hasPermission(user: AuthenticatedUser | null | undefined, permission: string) {
  const permissions = user?.permissions ?? [];
  return permissions.includes("*") || permissions.includes(permission);
}

export function isTeamAdmin(user: AuthenticatedUser | null | undefined, teamId: string) {
  return (user?.team_memberships ?? []).some(
    (membership) => membership.team_id === teamId && membership.role === "team_admin",
  );
}

export function hasAnyTeamMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.team_memberships ?? []).length > 0;
}

export function hasAnyTeamAdminMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.team_memberships ?? []).some((membership) => membership.role === "team_admin");
}

export function canViewWorkspace(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "teams.view") ||
    hasPermission(user, "projects.view") ||
    hasAnyTeamMembership(user)
  );
}

export function canManageKeys(user: AuthenticatedUser | null | undefined) {
  return hasPermission(user, "keys.manage") || hasAnyTeamAdminMembership(user);
}
