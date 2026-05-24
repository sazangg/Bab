import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { ApiDocsPage } from "@/features/api-docs/pages/ApiDocsPage";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { AllocationsPage } from "@/features/allocations/pages/AllocationsPage";
import { DesignSystemPage } from "@/features/design-system/pages/DesignSystemPage";
import { GuardrailsPage } from "@/features/guardrails/pages/GuardrailsPage";
import { DashboardHomePage } from "@/features/home/pages/DashboardHomePage";
import { KeyDetailPage } from "@/features/projects/pages/KeyDetailPage";
import { ProjectDetailPage } from "@/features/projects/pages/ProjectDetailPage";
import { ProjectsPage } from "@/features/projects/pages/ProjectsPage";
import { ProviderDetailPage } from "@/features/providers/pages/ProviderDetailPage";
import { ProvidersPage } from "@/features/providers/pages/ProvidersPage";
import { SettingsPage } from "@/features/settings/pages/SettingsPage";
import { TeamDetailPage } from "@/features/teams/pages/TeamDetailPage";
import { TeamsPage } from "@/features/teams/pages/TeamsPage";
import { VirtualKeysPage } from "@/features/virtual-keys/pages/VirtualKeysPage";

import { ActivityPage } from "@/features/activity/pages/ActivityPage";
import { UsagePage } from "@/features/usage/pages/UsagePage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>
      <Route element={<AuthGate />}>
        <Route element={<DashboardLayout />}>
          <Route path="/" element={<DashboardHomePage />} />
          <Route path="/teams" element={<TeamsPage />} />
          <Route path="/teams/:teamId" element={<TeamDetailPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/projects/:projectId/keys/:keyId" element={<KeyDetailPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/providers/:providerId" element={<ProviderDetailPage />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/api-docs" element={<ApiDocsPage />} />
          <Route path="/allocations" element={<AllocationsPage />} />
          <Route path="/virtual-keys" element={<VirtualKeysPage />} />
          <Route path="/guardrails" element={<GuardrailsPage />} />
          <Route path="/design-system" element={<DesignSystemPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
