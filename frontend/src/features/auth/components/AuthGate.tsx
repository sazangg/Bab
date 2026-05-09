import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useRefreshApiV1AuthRefreshPost } from "@/shared/api/generated/auth/auth";
import { useAuthStore } from "@/features/auth/model/auth-store";

export function AuthGate() {
  const location = useLocation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);
  const [refreshChecked, setRefreshChecked] = useState(isAuthenticated);
  const refreshMutation = useRefreshApiV1AuthRefreshPost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 200) {
          setSession(response.data.access_token);
        }
      },
      onError: () => {
        clearSession();
      },
      onSettled: () => {
        setRefreshChecked(true);
      },
    },
  });

  useEffect(() => {
    if (!isAuthenticated && !refreshChecked && !refreshMutation.isPending) {
      refreshMutation.mutate();
    }
  }, [isAuthenticated, refreshChecked, refreshMutation]);

  if (!refreshChecked) {
    return <p className="text-sm text-muted-foreground">Checking session...</p>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
