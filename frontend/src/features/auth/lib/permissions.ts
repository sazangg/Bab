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

export function canViewTeam(user: AuthenticatedUser | null | undefined, teamId: string) {
  return (
    hasPermission(user, "teams.view") ||
    (user?.team_memberships ?? []).some((membership) => membership.team_id === teamId)
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
  return (user?.project_memberships ?? []).some(
    (membership) => membership.role === "project_admin",
  );
}

export function canViewWorkspace(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "teams.view") ||
    hasPermission(user, "projects.view") ||
    hasAnyTeamMembership(user)
  );
}

export function canViewUsage(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "usage.view") ||
    hasAnyDirectTeamMembership(user) ||
    hasAnyProjectMembership(user)
  );
}

export function canViewActivity(user: AuthenticatedUser | null | undefined) {
  return (
    hasPermission(user, "activity.view") ||
    hasAnyDirectTeamMembership(user) ||
    hasAnyProjectMembership(user)
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

export function workspaceLandingPath(user: AuthenticatedUser | null | undefined) {
  if (canViewDashboardHome(user)) return "/";
  if (hasAnyDirectTeamMembership(user)) return "/teams";
  if (hasAnyProjectMembership(user)) return "/projects";
  if (canManageKeys(user)) return "/virtual-keys";
  if (canViewUsage(user)) return "/usage";
  if (canViewActivity(user)) return "/activity";
  return null;
}
