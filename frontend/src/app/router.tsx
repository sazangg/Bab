import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { ProvidersProjectsPage } from "@/features/providers-projects/pages/ProvidersProjectsPage";
import { SetupRedirect } from "@/features/setup/components/SetupRedirect";
import { SetupPage } from "@/features/setup/pages/SetupPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route element={<SetupRedirect requireSetup />}>
          <Route path="/setup" element={<SetupPage />} />
        </Route>
        <Route element={<SetupRedirect requireSetup={false} />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>
      </Route>
      <Route element={<SetupRedirect requireSetup={false} />}>
        <Route element={<AuthGate />}>
          <Route element={<DashboardLayout />}>
            <Route path="/" element={<ProvidersProjectsPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
