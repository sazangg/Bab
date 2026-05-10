import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuditPage } from "@/features/audit/pages/AuditPage";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { LogsPage } from "@/features/logs/pages/LogsPage";
import { OverviewPage } from "@/features/overview/pages/OverviewPage";
import { KeyDetailPage } from "@/features/projects/pages/KeyDetailPage";
import { ProjectDetailPage } from "@/features/projects/pages/ProjectDetailPage";
import { ProjectsPage } from "@/features/projects/pages/ProjectsPage";
import { ProvidersPage } from "@/features/providers/pages/ProvidersPage";
import { SettingsPage } from "@/features/settings/pages/SettingsPage";
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
            <Route path="/" element={<OverviewPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="/projects/:projectId/keys/:keyId" element={<KeyDetailPage />} />
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
