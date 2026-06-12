import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
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
    return (
      <main
        className="grid min-h-svh place-items-center bg-background p-6 text-foreground"
        aria-label="Checking session"
      >
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Checking session...
        </div>
      </main>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
