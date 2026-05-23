import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { DesignSystemPage } from "@/features/design-system/pages/DesignSystemPage";
import { DashboardHomePage } from "@/features/home/pages/DashboardHomePage";
import { KeyDetailPage } from "@/features/projects/pages/KeyDetailPage";
import { ProjectDetailPage } from "@/features/projects/pages/ProjectDetailPage";
import { ProjectsPage } from "@/features/projects/pages/ProjectsPage";
import { ProviderDetailPage } from "@/features/providers/pages/ProviderDetailPage";
import { ProvidersPage } from "@/features/providers/pages/ProvidersPage";
import { TeamDetailPage } from "@/features/teams/pages/TeamDetailPage";
import { TeamsPage } from "@/features/teams/pages/TeamsPage";
import { Route as RouteIcon, Settings, ShieldCheck } from "lucide-react";

import { ComingSoonPage } from "@/shared/components/ComingSoonPage";
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
          <Route
            path="/settings"
            element={
              <ComingSoonPage
                title="Settings"
                description="Organization profile, gateway defaults, and administrative controls."
                icon={Settings}
                outcomes={[
                  "Organization identity and gateway defaults.",
                  "Security, API, and runtime configuration.",
                  "Future user and role management once non-admin views are derived.",
                ]}
              />
            }
          />
          <Route
            path="/allocations"
            element={
              <ComingSoonPage
                title="Allocations"
                description="Cross-cutting inventory of team and project resource allocations."
                icon={RouteIcon}
                outcomes={[
                  "All active and inactive allocations in one operational view.",
                  "Parent-child allocation context across teams and projects.",
                  "Limit pressure, model coverage, and pool coverage by allocation.",
                ]}
              />
            }
          />
          <Route
            path="/guardrails"
            element={
              <ComingSoonPage
                title="Guardrails"
                description="Future policy surface for safety, data, and routing constraints."
                icon={ShieldCheck}
                outcomes={[
                  "Org-wide and scoped policy rules.",
                  "Model, data, and request controls that complement allocations.",
                  "Clear enforcement outcomes visible from project and key views.",
                ]}
              />
            }
          />
          <Route path="/design-system" element={<DesignSystemPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
