import { ShieldAlert } from "lucide-react";
import { Outlet } from "react-router-dom";

import { Card, CardContent } from "@/components/ui/card";
import {
  canManageKeys,
  canViewDashboardHome,
  canViewWorkspace,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";

type ProtectedRouteProps = {
  permission?: string;
  allowWorkspaceScope?: boolean;
  requireTeamAdminScope?: boolean;
  requireKeyManager?: boolean;
  allowDashboardHome?: boolean;
};

export function ProtectedRoute({
  permission,
  allowWorkspaceScope = false,
  requireTeamAdminScope = false,
  requireKeyManager = false,
  allowDashboardHome = false,
}: ProtectedRouteProps) {
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;

  if (currentUserQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Checking access...</p>;
  }

  const allowed =
    (permission ? hasPermission(currentUser, permission) : false) ||
    (allowWorkspaceScope ? canViewWorkspace(currentUser) : false) ||
    (requireTeamAdminScope ? hasAnyTeamAdminMembership(currentUser) : false) ||
    (requireKeyManager ? canManageKeys(currentUser) : false) ||
    (allowDashboardHome ? canViewDashboardHome(currentUser) : false) ||
    (!permission &&
      !allowWorkspaceScope &&
      !requireTeamAdminScope &&
      !requireKeyManager &&
      !allowDashboardHome);

  if (!allowed) {
    if (!canViewDashboardHome(currentUser)) {
      return <NoAccessPage />;
    }
    return <ForbiddenPage />;
  }

  return <Outlet />;
}

export function NoAccessPage() {
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
              Your organization account is active, but no team role or gateway permissions have
              been assigned yet. Ask an organization admin to add you to a team or grant the
              permissions needed for your work.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function ForbiddenPage() {
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
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
