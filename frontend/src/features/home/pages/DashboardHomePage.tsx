import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Building2,
  FlaskConical,
  FolderKanban,
  GitBranch,
  Info,
  KeyRound,
  ListChecks,
  Plug,
  Settings,
  ShieldCheck,
  Users,
  WalletCards,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { useGetOrganizationUsageSummaryApiV1UsageSummaryGet } from "@/shared/api/generated/usage/usage";
import { useListVirtualKeyInventoryApiV1VirtualKeysGet } from "@/shared/api/generated/virtual-keys/virtual-keys";
import type { ActivityEventPageResponse, ActivityEventResponse } from "@/shared/api/generated/schemas";
import { httpClient } from "@/shared/api/http-client";
import {
  canViewActivity,
  canViewOrgAdminSurface,
  canViewUsage,
  canViewWorkspace,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatCard } from "@/shared/components/StatCard";
import { formatCents } from "@/shared/lib/format-currency";
import { buildSetupStatus } from "@/features/setup/lib/setup-status";

export function DashboardHomePage() {
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const isAdmin = canViewOrgAdminSurface(currentUser);
  const showUsage = canViewUsage(currentUser);
  const showActivity = canViewActivity(currentUser);

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const keysQuery = useListVirtualKeyInventoryApiV1VirtualKeysGet({ limit: 100 });
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet(
    { window: "30d" },
    { query: { enabled: showUsage } },
  );
  const activityQuery = useQuery({
    queryKey: ["home-recent-activity"],
    enabled: showActivity,
    queryFn: async () => {
      const response = await httpClient.get<ActivityEventPageResponse>("/api/v1/activity", {
        params: { limit: 6 },
      });
      return response.data;
    },
  });

  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const keysPage = keysQuery.data?.status === 200 ? keysQuery.data.data : null;
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const recentActivity = activityQuery.data?.items ?? [];

  const activeProviders = providers.filter((provider) => provider.is_active);
  const readyProviders = providers.filter((provider) => provider.readiness?.is_ready);
  const keys = keysPage?.items ?? [];
  const usableKeys = keys.filter((key) => key.is_usable);
  const setupStatus = buildSetupStatus({
    providersCount: providers.length,
    readyProvidersCount: readyProviders.length,
    teamsCount: teams.length,
    projectsCount: projects.length,
    usableVirtualKeysCount: usableKeys.length,
    gatewayRequestsCount: usage?.totals.requests ?? 0,
    accessPoliciesCount: 0,
    limitPoliciesCount: 0,
    guardrailPoliciesCount: 0,
  });

  const primaryAction = isAdmin
    ? !setupStatus.isComplete
      ? { label: "Open setup", to: "/setup", icon: ListChecks }
      : { label: "Open Playground", to: "/playground", icon: FlaskConical }
    : showUsage
      ? { label: "View usage", to: "/usage", icon: WalletCards }
      : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Home"
        description={
          isAdmin
            ? "Set up the gateway, track spend, and jump into the surfaces you manage."
            : "Organization usage, recent activity, and the surfaces you can view."
        }
        actions={
          primaryAction ? (
            <Button asChild>
              <Link to={primaryAction.to}>
                <primaryAction.icon data-icon="inline-start" />
                {primaryAction.label}
              </Link>
            </Button>
          ) : null
        }
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {showUsage ? (
          <StatCard
            label="30-day spend"
            value={formatCents(usage?.totals.cost_cents)}
            hint={`${(usage?.totals.requests ?? 0).toLocaleString()} requests`}
            icon={WalletCards}
          />
        ) : null}
        <StatCard
          label="Providers"
          value={`${readyProviders.length}/${activeProviders.length}`}
          hint="ready / active"
          icon={Plug}
        />
        <StatCard
          label="Projects"
          value={projects.length}
          hint={`${teams.length} ${teams.length === 1 ? "team" : "teams"}`}
          icon={FolderKanban}
        />
        <StatCard
          label="Virtual keys"
          value={`${usableKeys.length}/${keys.length}`}
          hint="usable / total"
          icon={KeyRound}
        />
      </div>

      {isAdmin && !setupStatus.isComplete ? (
        <SetupCallout
          completed={setupStatus.completedRequiredCount}
          total={setupStatus.totalRequiredCount}
          nextLabel={setupStatus.nextRequiredStep?.label}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        {showActivity ? (
          <RecentActivityCard
            events={recentActivity}
            isLoading={activityQuery.isPending}
            isError={activityQuery.isError}
          />
        ) : null}
        <QuickLinksCard
          className={showActivity ? undefined : "lg:col-span-2"}
          links={[
            { show: true, label: "Providers", description: "Credentials, pools, models", to: "/providers", icon: Plug },
            { show: canViewWorkspace(currentUser), label: "Policies", description: "Routes, budgets, caps", to: "/policies", icon: GitBranch },
            { show: canViewWorkspace(currentUser), label: "Guardrails", description: "Model/provider/pool rules", to: "/guardrails", icon: ShieldCheck },
            { show: true, label: "Teams & projects", description: "Workspace structure", to: "/teams", icon: Building2 },
            { show: showUsage, label: "Usage", description: "Spend and request records", to: "/usage", icon: WalletCards },
            { show: showActivity, label: "Activity", description: "Admin & runtime events", to: "/activity", icon: Activity },
            { show: hasPermission(currentUser, "members.manage"), label: "Users", description: "Members, roles, invites", to: "/users", icon: Users },
            { show: hasPermission(currentUser, "settings.manage"), label: "Settings", description: "Org & gateway defaults", to: "/settings", icon: Settings },
          ]}
        />
      </div>
    </div>
  );
}

function SetupCallout({
  completed,
  total,
  nextLabel,
}: {
  completed: number;
  total: number;
  nextLabel?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Setup needs attention</CardTitle>
        <CardDescription>
            {completed} of {total} required steps complete
            {nextLabel ? `. Next: ${nextLabel}.` : "."}
        </CardDescription>
        </div>
        <Button asChild>
          <Link to="/setup">
            Open setup
            <ArrowRight data-icon="inline-end" />
          </Link>
        </Button>
      </CardHeader>
    </Card>
  );
}

function RecentActivityCard({
  events,
  isLoading,
  isError,
}: {
  events: ActivityEventResponse[];
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Recent activity</CardTitle>
          <CardDescription>Latest admin changes and runtime gateway events.</CardDescription>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link to="/activity">
            View all
            <ArrowRight data-icon="inline-end" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading activity...</p>
        ) : isError ? (
          <p className="text-sm text-muted-foreground">Activity could not be loaded.</p>
        ) : events.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No activity yet"
            description="Admin changes and proxy events will appear here."
          />
        ) : (
          <div className="flex flex-col divide-y divide-border">
            {events.map((event) => {
              const Icon =
                event.severity === "error"
                  ? XCircle
                  : event.severity === "warning"
                    ? AlertTriangle
                    : Info;
              return (
                <div key={event.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                  <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{event.message}</div>
                    <div className="text-xs text-muted-foreground">
                      {event.actor_email ?? "Gateway runtime"} ·{" "}
                      {new Date(event.created_at).toLocaleString()}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type QuickLink = {
  show: boolean;
  label: string;
  description: string;
  to: string;
  icon: LucideIcon;
};

function QuickLinksCard({ links, className }: { links: QuickLink[]; className?: string }) {
  const visible = links.filter((link) => link.show);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Quick links</CardTitle>
        <CardDescription>Jump to the surfaces you can use.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-2">
        {visible.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="group flex items-start gap-3 rounded-md border bg-background p-3 transition-colors hover:bg-muted/40"
          >
            <link.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
            <div className="min-w-0">
              <div className="text-sm font-medium">{link.label}</div>
              <div className="text-xs text-muted-foreground">{link.description}</div>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
