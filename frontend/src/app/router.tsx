import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { OverviewPage } from "@/features/overview/pages/OverviewPage";
import { KeyDetailPage } from "@/features/projects/pages/KeyDetailPage";
import { ProjectDetailPage } from "@/features/projects/pages/ProjectDetailPage";
import { ProjectsPage } from "@/features/projects/pages/ProjectsPage";
import { ProviderDetailPage } from "@/features/providers/pages/ProviderDetailPage";
import { ProvidersPage } from "@/features/providers/pages/ProvidersPage";
import { TeamDetailPage } from "@/features/teams/pages/TeamDetailPage";
import { TeamsPage } from "@/features/teams/pages/TeamsPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>
      <Route element={<AuthGate />}>
        <Route element={<DashboardLayout />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/teams" element={<TeamsPage />} />
          <Route path="/teams/:teamId" element={<TeamDetailPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/projects/:projectId/keys/:keyId" element={<KeyDetailPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/providers/:providerId" element={<ProviderDetailPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
