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

export function isProjectAdmin(user: AuthenticatedUser | null | undefined, projectId: string) {
  return (user?.project_memberships ?? []).some(
    (membership) => membership.project_id === projectId && membership.role === "project_admin",
  );
}

export function hasAnyTeamMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.team_memberships ?? []).length > 0 || (user?.project_memberships ?? []).length > 0;
}

export function hasAnyDirectTeamMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.team_memberships ?? []).length > 0;
}

export function hasAnyProjectMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.project_memberships ?? []).length > 0;
}

export function hasAnyTeamAdminMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.team_memberships ?? []).some((membership) => membership.role === "team_admin");
}

export function hasAnyProjectAdminMembership(user: AuthenticatedUser | null | undefined) {
  return (user?.project_memberships ?? []).some((membership) => membership.role === "project_admin");
}

export function canViewWorkspace(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "teams.view") ||
    hasPermission(user, "projects.view") ||
    hasAnyTeamMembership(user)
  );
}

export function canManageKeys(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "keys.manage") ||
    hasAnyTeamAdminMembership(user) ||
    (user?.project_memberships ?? []).some((membership) => membership.role === "project_admin")
  );
}

export function canViewDashboardHome(user: AuthenticatedUser | null | undefined) {
  return user?.role === "org_owner" || user?.role === "org_admin" || user?.role === "org_viewer";
}

export function canViewOrgAdminSurface(user: AuthenticatedUser | null | undefined) {
  return user?.role === "org_owner" || user?.role === "org_admin";
}
