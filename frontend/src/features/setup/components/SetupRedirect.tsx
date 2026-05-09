import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useGetSetupStatusApiV1SetupStatusGet } from "@/shared/api/generated/setup/setup";

type SetupRedirectProps = {
  requireSetup: boolean;
};

export function SetupRedirect({ requireSetup }: SetupRedirectProps) {
  const location = useLocation();
  const setupStatusQuery = useGetSetupStatusApiV1SetupStatusGet();
  const setupRequired = setupStatusQuery.data?.data.setup_required;

  if (setupStatusQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Checking setup...</p>;
  }

  if (setupStatusQuery.isError || setupRequired === undefined) {
    return <p className="text-sm text-destructive">Setup status is unavailable.</p>;
  }

  if (requireSetup && !setupRequired) {
    return <Navigate to="/login" replace />;
  }

  if (!requireSetup && setupRequired && location.pathname !== "/setup") {
    return <Navigate to="/setup" replace />;
  }

  return <Outlet />;
}
