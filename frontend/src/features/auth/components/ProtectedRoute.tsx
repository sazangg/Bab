import { ShieldAlert } from "lucide-react";
import { Outlet } from "react-router-dom";

import { Card, CardContent } from "@/components/ui/card";
import {
  canManageKeys,
  canViewWorkspace,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { PageHeader } from "@/shared/components/PageHeader";

type ProtectedRouteProps = {
  permission?: string;
  allowWorkspaceScope?: boolean;
  requireTeamAdminScope?: boolean;
  requireKeyManager?: boolean;
};

export function ProtectedRoute({
  permission,
  allowWorkspaceScope = false,
  requireTeamAdminScope = false,
  requireKeyManager = false,
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
    (!permission && !allowWorkspaceScope && !requireTeamAdminScope && !requireKeyManager);

  if (!allowed) {
    return <ForbiddenPage />;
  }

  return <Outlet />;
}

export function ForbiddenPage() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Card className="w-full max-w-lg">
        <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
          <div className="rounded-full bg-muted p-3 text-muted-foreground">
            <ShieldAlert className="size-6" />
          </div>
          <PageHeader
            title="Access denied"
            description="Your current role does not include access to this surface."
          />
        </CardContent>
      </Card>
    </div>
  );
}
