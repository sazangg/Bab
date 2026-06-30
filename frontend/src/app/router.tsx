import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { AuthGate } from "@/features/auth/components/AuthGate";
import { ProtectedRoute } from "@/features/auth/components/ProtectedRoute";
const AcceptInvitePage = lazy(() =>
  import("@/features/auth/pages/AcceptInvitePage").then((module) => ({
    default: module.AcceptInvitePage,
  })),
);
const AccessPolicyDetailPage = lazy(() =>
  import("@/features/policies/pages/PoliciesPage").then((module) => ({
    default: module.AccessPolicyDetailPage,
  })),
);
const ActivityPage = lazy(() =>
  import("@/features/activity/pages/ActivityPage").then((module) => ({
    default: module.ActivityPage,
  })),
);
const ApiDocsPage = lazy(() =>
  import("@/features/api-docs/pages/ApiDocsPage").then((module) => ({
    default: module.ApiDocsPage,
  })),
);
const AuditPage = lazy(() =>
  import("@/features/audit/pages/AuditPage").then((module) => ({
    default: module.AuditPage,
  })),
);
const DashboardHomePage = lazy(() =>
  import("@/features/home/pages/DashboardHomePage").then((module) => ({
    default: module.DashboardHomePage,
  })),
);
const DesignSystemPage = lazy(() =>
  import("@/features/design-system/pages/DesignSystemPage").then((module) => ({
    default: module.DesignSystemPage,
  })),
);
const GuardrailsPage = lazy(() =>
  import("@/features/guardrails/pages/GuardrailsPage").then((module) => ({
    default: module.GuardrailsPage,
  })),
);
const GatewayHistoryPage = lazy(() =>
  import("@/features/gateway-history/pages/GatewayHistoryPage").then((module) => ({
    default: module.GatewayHistoryPage,
  })),
);
const KeyDetailPage = lazy(() =>
  import("@/features/projects/pages/KeyDetailPage").then((module) => ({
    default: module.KeyDetailPage,
  })),
);
const LimitPolicyDetailPage = lazy(() =>
  import("@/features/policies/pages/PoliciesPage").then((module) => ({
    default: module.LimitPolicyDetailPage,
  })),
);
const LoginPage = lazy(() =>
  import("@/features/auth/pages/LoginPage").then((module) => ({
    default: module.LoginPage,
  })),
);
const PlaygroundPage = lazy(() =>
  import("@/features/playground/pages/PlaygroundPage").then((module) => ({
    default: module.PlaygroundPage,
  })),
);
const PoliciesPage = lazy(() =>
  import("@/features/policies/pages/PoliciesPage").then((module) => ({
    default: module.PoliciesPage,
  })),
);
const ProjectDetailPage = lazy(() =>
  import("@/features/projects/pages/ProjectDetailPage").then((module) => ({
    default: module.ProjectDetailPage,
  })),
);
const ProjectsPage = lazy(() =>
  import("@/features/projects/pages/ProjectsPage").then((module) => ({
    default: module.ProjectsPage,
  })),
);
const ProviderDetailPage = lazy(() =>
  import("@/features/providers/pages/ProviderDetailPage").then((module) => ({
    default: module.ProviderDetailPage,
  })),
);
const ProvidersPage = lazy(() =>
  import("@/features/providers/pages/ProvidersPage").then((module) => ({
    default: module.ProvidersPage,
  })),
);
const SettingsPage = lazy(() =>
  import("@/features/settings/pages/SettingsPage").then((module) => ({
    default: module.SettingsPage,
  })),
);
const SetupPage = lazy(() =>
  import("@/features/setup/pages/SetupPage").then((module) => ({
    default: module.SetupPage,
  })),
);
const TeamDetailPage = lazy(() =>
  import("@/features/teams/pages/TeamDetailPage").then((module) => ({
    default: module.TeamDetailPage,
  })),
);
const TeamsPage = lazy(() =>
  import("@/features/teams/pages/TeamsPage").then((module) => ({
    default: module.TeamsPage,
  })),
);
const UsagePage = lazy(() =>
  import("@/features/usage/pages/UsagePage").then((module) => ({
    default: module.UsagePage,
  })),
);
const UsersPage = lazy(() =>
  import("@/features/users/pages/UsersPage").then((module) => ({
    default: module.UsersPage,
  })),
);
const VirtualKeysPage = lazy(() =>
  import("@/features/virtual-keys/pages/VirtualKeysPage").then((module) => ({
    default: module.VirtualKeysPage,
  })),
);

const isProductionBuild = import.meta.env.PROD;

function ProbePage({ kind }: { kind: "health" | "readyz" }) {
  return (
    <main className="grid min-h-svh place-items-center bg-background p-6 text-foreground">
      <div className="w-full max-w-lg rounded-md border bg-card p-6 shadow-sm">
        <p className="text-sm text-muted-foreground">Bab probe</p>
        <h1 className="mt-1 text-2xl font-semibold">
          {kind === "health" ? "Health" : "Readiness"}
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Use the backend endpoint{" "}
          <code className="rounded bg-muted px-1 py-0.5">
            {kind === "health" ? "/health" : "/readyz"}
          </code>{" "}
          or{" "}
          <code className="rounded bg-muted px-1 py-0.5">
            {kind === "health" ? "/api/v1/health" : "/api/v1/readyz"}
          </code>
          .
        </p>
      </div>
    </main>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/health" element={<ProbePage kind="health" />} />
        <Route path="/readyz" element={<ProbePage kind="readyz" />} />
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/accept-invite" element={<AcceptInvitePage />} />
        </Route>
        <Route element={<AuthGate />}>
          <Route element={<DashboardLayout />}>
          <Route element={<ProtectedRoute allowDashboardHome />}>
            <Route path="/" element={<DashboardHomePage />} />
          </Route>
          <Route element={<ProtectedRoute requireOrgAdminSurface />}>
            <Route path="/setup" element={<SetupPage />} />
          </Route>
          <Route element={<ProtectedRoute allowTeamScope />}>
            <Route path="/teams" element={<TeamsPage />} />
            <Route path="/teams/:teamId" element={<TeamDetailPage />} />
          </Route>
          <Route element={<ProtectedRoute allowWorkspaceScope />}>
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="/projects/:projectId/keys/:keyId" element={<KeyDetailPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="policies.view" requireScopedAdmin />}>
            <Route path="/policies" element={<PoliciesPage />} />
            <Route path="/policies/access/:policyId" element={<AccessPolicyDetailPage />} />
            <Route path="/policies/limits/:policyId" element={<LimitPolicyDetailPage />} />
          </Route>
          <Route element={<ProtectedRoute requireKeyManager />}>
            <Route path="/virtual-keys" element={<VirtualKeysPage />} />
          </Route>
          <Route element={<ProtectedRoute requireKeyManager />}>
            <Route path="/playground" element={<PlaygroundPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="providers.view" />}>
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/providers/:providerId" element={<ProviderDetailPage />} />
          </Route>
          <Route element={<ProtectedRoute allowUsageScope />}>
            <Route path="/usage" element={<UsagePage />} />
          </Route>
          <Route element={<ProtectedRoute allowGatewayHistoryScope />}>
            <Route path="/gateway-history" element={<GatewayHistoryPage />} />
          </Route>
          <Route element={<ProtectedRoute allowActivityScope />}>
            <Route path="/activity" element={<ActivityPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="audit.view" />}>
            <Route path="/audit" element={<AuditPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="members.manage" requireScopedAdmin />}>
            <Route path="/users" element={<UsersPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="settings.view" />}>
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route element={<ProtectedRoute requireKeyManager />}>
            <Route path="/api-docs" element={<ApiDocsPage />} />
          </Route>
          <Route element={<ProtectedRoute permission="guardrails.view" requireScopedAdmin />}>
            <Route path="/guardrails" element={<GuardrailsPage />} />
          </Route>
          {!isProductionBuild ? (
            <Route path="/design-system" element={<DesignSystemPage />} />
          ) : null}
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Suspense>
  );
}

function RouteLoading() {
  return (
    <main className="grid min-h-40 place-items-center p-6">
      <p className="text-sm text-muted-foreground">Loading...</p>
    </main>
  );
}
