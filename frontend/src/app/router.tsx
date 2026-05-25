import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { ProtectedRoute } from "@/features/auth/components/ProtectedRoute";
import { ApiDocsPage } from "@/features/api-docs/pages/ApiDocsPage";
import { AuditPage } from "@/features/audit/pages/AuditPage";
import { AcceptInvitePage } from "@/features/auth/pages/AcceptInvitePage";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { AllocationsPage } from "@/features/allocations/pages/AllocationsPage";
import { DesignSystemPage } from "@/features/design-system/pages/DesignSystemPage";
import { GuardrailsPage } from "@/features/guardrails/pages/GuardrailsPage";
import { DashboardHomePage } from "@/features/home/pages/DashboardHomePage";
import { KeyDetailPage } from "@/features/projects/pages/KeyDetailPage";
import { PlaygroundPage } from "@/features/playground/pages/PlaygroundPage";
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
import { UsersPage } from "@/features/users/pages/UsersPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
      </Route>
      <Route element={<AuthGate />}>
        <Route element={<DashboardLayout />}>
          <Route path="/" element={<DashboardHomePage />} />
          <Route element={<ProtectedRoute allowWorkspaceScope />}>
            <Route path="/teams" element={<TeamsPage />} />
            <Route path="/teams/:teamId" element={<TeamDetailPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="/projects/:projectId/keys/:keyId" element={<KeyDetailPage />} />
            <Route path="/allocations" element={<AllocationsPage />} />
          </Route>
          <Route element={<ProtectedRoute requireKeyManager />}>
            <Route path="/virtual-keys" element={<VirtualKeysPage />} />
            <Route path="/playground" element={<PlaygroundPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="providers.view" />}>
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/providers/:providerId" element={<ProviderDetailPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="usage.view" />}>
            <Route path="/usage" element={<UsagePage />} />
          </Route>
          <Route element={<ProtectedRoute permission="activity.view" />}>
            <Route path="/activity" element={<ActivityPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="audit.view" />}>
            <Route path="/audit" element={<AuditPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="members.manage" />}>
            <Route path="/users" element={<UsersPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="settings.view" />}>
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route element={<ProtectedRoute requireKeyManager />}>
            <Route path="/api-docs" element={<ApiDocsPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="guardrails.view" />}>
            <Route path="/guardrails" element={<GuardrailsPage />} />
          </Route>
          <Route path="/design-system" element={<DesignSystemPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
