import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "@/features/auth/model/auth-store";
import { refreshAccessToken } from "@/shared/api/http-client";

export function AuthGate() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [refreshChecked, setRefreshChecked] = useState(isAuthenticated);

  useEffect(() => {
    if (isAuthenticated || refreshChecked) return;

    void refreshAccessToken()
      .catch(() => {
        queryClient.clear();
      })
      .finally(() => {
        setRefreshChecked(true);
      });
  }, [isAuthenticated, queryClient, refreshChecked]);

  if (!refreshChecked) {
    return <p className="text-sm text-muted-foreground">Checking session...</p>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
