import { LoaderCircle, ShieldAlert } from "lucide-react";
import { Link, Navigate, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  canViewActivity,
  canManageKeys,
  canViewUsage,
  canViewOrgAdminSurface,
  canViewDashboardHome,
  canViewWorkspace,
  hasAnyDirectTeamMembership,
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
  workspaceLandingPath,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";

type ProtectedRouteProps = {
  permission?: string;
  allowWorkspaceScope?: boolean;
  allowTeamScope?: boolean;
  requireTeamAdminScope?: boolean;
  requireKeyManager?: boolean;
  requireScopedAdmin?: boolean;
  allowUsageScope?: boolean;
  allowActivityScope?: boolean;
  allowDashboardHome?: boolean;
  requireOrgAdminSurface?: boolean;
};

export function ProtectedRoute({
  permission,
  allowWorkspaceScope = false,
  allowTeamScope = false,
  requireTeamAdminScope = false,
  requireKeyManager = false,
  requireScopedAdmin = false,
  allowUsageScope = false,
  allowActivityScope = false,
  allowDashboardHome = false,
  requireOrgAdminSurface = false,
}: ProtectedRouteProps) {
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;

  if (currentUserQuery.isPending) {
    return (
      <div className="grid min-h-[40vh] place-items-center" aria-label="Checking access">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Checking access...
        </div>
      </div>
    );
  }

  if (currentUserQuery.isError) {
    return (
      <div className="grid min-h-[50vh] place-items-center">
        <Card className="w-full max-w-lg">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <div className="rounded-full bg-muted p-3 text-muted-foreground">
              <ShieldAlert className="size-6" />
            </div>
            <div className="space-y-2">
              <h1 className="text-xl font-semibold">Could not check access</h1>
              <p className="text-sm text-muted-foreground">
                Bab could not load your current permissions. Check the connection and try again.
              </p>
            </div>
            <Button type="button" onClick={() => void currentUserQuery.refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const allowed =
    (permission ? hasPermission(currentUser, permission) : false) ||
    (allowWorkspaceScope ? canViewWorkspace(currentUser) : false) ||
    (allowTeamScope
      ? hasPermission(currentUser, "teams.view") || hasAnyDirectTeamMembership(currentUser)
      : false) ||
    (requireTeamAdminScope ? hasAnyTeamAdminMembership(currentUser) : false) ||
    (requireKeyManager ? canManageKeys(currentUser) : false) ||
    (requireScopedAdmin
      ? hasAnyTeamAdminMembership(currentUser) || hasAnyProjectAdminMembership(currentUser)
      : false) ||
    (allowUsageScope ? canViewUsage(currentUser) : false) ||
    (allowActivityScope ? canViewActivity(currentUser) : false) ||
    (allowDashboardHome ? canViewDashboardHome(currentUser) : false) ||
    (requireOrgAdminSurface ? canViewOrgAdminSurface(currentUser) : false) ||
    (!permission &&
      !allowWorkspaceScope &&
      !allowTeamScope &&
      !requireTeamAdminScope &&
      !requireKeyManager &&
      !requireScopedAdmin &&
      !allowUsageScope &&
      !allowActivityScope &&
      !allowDashboardHome &&
      !requireOrgAdminSurface);

  if (!allowed) {
    const landingPath = workspaceLandingPath(currentUser);
    if (allowDashboardHome && landingPath && landingPath !== "/") {
      return <Navigate to={landingPath} replace />;
    }
    if (!landingPath) {
      return <NoAccessPage email={currentUser?.email} role={currentUser?.role} />;
    }
    return (
      <ForbiddenPage
        email={currentUser?.email}
        role={currentUser?.role}
        landingPath={landingPath}
      />
    );
  }

  return <Outlet />;
}

export function NoAccessPage({ email, role }: { email?: string; role?: string }) {
  return (
    <div className="grid min-h-[calc(100svh-12rem)] place-items-center">
      <Card className="w-full max-w-lg">
        <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
          <div className="rounded-full bg-muted p-3 text-muted-foreground">
            <ShieldAlert className="size-6" />
          </div>
          <div className="space-y-2">
            <h1 className="text-xl font-semibold">No workspace access yet</h1>
            <p className="text-sm text-muted-foreground">
              Your organization account is active, but no team role or gateway permissions have been
              assigned yet. Ask an organization admin to add you to a team or grant the permissions
              needed for your work.
            </p>
            {email ? (
              <p className="text-xs text-muted-foreground">
                Signed in as {email} · {formatRole(role)}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function ForbiddenPage({
  email,
  role,
  landingPath,
}: {
  email?: string;
  role?: string;
  landingPath?: string | null;
}) {
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <Card className="w-full max-w-lg">
        <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
          <div className="rounded-full bg-muted p-3 text-muted-foreground">
            <ShieldAlert className="size-6" />
          </div>
          <div className="space-y-2">
            <h1 className="text-xl font-semibold">Access denied</h1>
            <p className="text-sm text-muted-foreground">
              Your current role does not include access to this surface.
            </p>
            {email ? (
              <p className="text-xs text-muted-foreground">
                Signed in as {email} · {formatRole(role)}
              </p>
            ) : null}
          </div>
          {landingPath ? (
            <Button asChild>
              <Link to={landingPath}>Go to your workspace</Link>
            </Button>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function formatRole(role?: string) {
  if (role === "org_owner") return "Org owner";
  if (role === "org_admin") return "Org admin";
  if (role === "org_viewer") return "Org viewer";
  if (role === "org_member") return "Org member";
  return "Unknown role";
}
