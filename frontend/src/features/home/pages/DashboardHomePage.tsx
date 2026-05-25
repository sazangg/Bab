import {
  Activity,
  AlertTriangle,
  Building2,
  CircleGauge,
  FolderKanban,
  KeyRound,
  Plug,
  Route,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { PageHeader } from "@/shared/components/PageHeader";

const setupSteps = [
  {
    label: "Connect providers",
    description: "Configure provider credentials, pools, and model offerings.",
    to: "/providers",
    icon: Plug,
  },
  {
    label: "Structure teams",
    description: "Create the organizational containers that own budgets.",
    to: "/teams",
    icon: Building2,
  },
  {
    label: "Create projects",
    description: "Attach projects to teams and issue scoped virtual keys.",
    to: "/projects",
    icon: FolderKanban,
  },
];

const attentionItems = [
  {
    label: "Allocation usage",
    description: "Review budget, limits, and usage from allocation cards.",
    icon: WalletCards,
  },
  {
    label: "Activity stream",
    description: "Audit admin changes and runtime gateway events.",
    icon: Activity,
  },
  {
    label: "Guardrails",
    description: "Assign model, provider, and pool policies across scopes.",
    icon: ShieldCheck,
  },
];

export function DashboardHomePage() {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();

  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const activeProviders = providers.filter((provider) => provider.is_active);
  const providersWithCredentials = providers.filter(
    (provider) => (provider.credential_summary?.active ?? 0) > 0,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Gateway home"
        description="Super-admin command center for provider readiness, workspace structure, and allocation control."
        actions={
          <Button asChild>
            <Link to="/providers">
              <Plug data-icon="inline-start" />
              Configure providers
            </Link>
          </Button>
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Active providers"
          value={activeProviders.length}
          detail={`${providersWithCredentials.length} with active credentials`}
          icon={Plug}
        />
        <MetricCard
          label="Teams"
          value={teams.length}
          detail="Workspace budget owners"
          icon={Building2}
        />
        <MetricCard
          label="Projects"
          value={projects.length}
          detail="Virtual key containers"
          icon={FolderKanban}
        />
        <MetricCard
          label="Gateway state"
          value={providersWithCredentials.length > 0 ? "Routable" : "Setup"}
          detail={
            providersWithCredentials.length > 0
              ? "At least one active credential"
              : "Add credentials to route traffic"
          }
          icon={CircleGauge}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <Card>
          <CardHeader className="border-b">
            <CardTitle>Operating flow</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-3">
              {setupSteps.map((step) => (
                <Link
                  key={step.label}
                  to={step.to}
                  className="group rounded-lg border bg-background p-4 transition-colors hover:bg-muted/50"
                >
                  <step.icon className="mb-4 size-5 text-muted-foreground transition-colors group-hover:text-foreground" />
                  <div className="font-medium">{step.label}</div>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{step.description}</p>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Attention</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {attentionItems.map((item) => (
              <div key={item.label} className="flex gap-3 rounded-lg border bg-background p-3">
                <item.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{item.label}</span>
                    <Badge variant="outline">Live</Badge>
                  </div>
                  <p className="mt-1 text-sm leading-5 text-muted-foreground">{item.description}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="border-b">
            <CardTitle>Resource model</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 text-sm">
              <FlowRow icon={Plug} label="Providers" value="Credentials, pools, models" />
              <FlowRow icon={Route} label="Allocations" value="Pools, model offerings, limits" />
              <FlowRow icon={KeyRound} label="Virtual keys" value="Project access to allocations" />
              <FlowRow icon={Activity} label="Usage" value="Append-only attribution records" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Navigation freeze</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
            <p>
              Organization views own gateway-wide administration: providers, usage, activity, and
              settings.
            </p>
            <p>
              Workspace views own domain structure: teams, projects, allocations, and future
              guardrails. Scoped usage appears inside those entities instead of as a second global
              usage product.
            </p>
            <div className="flex items-center gap-2 rounded-lg border bg-amber-500/10 p-3 text-amber-700 dark:text-amber-300">
              <AlertTriangle className="size-4 shrink-0" />
              <span>
                Navigation entries now point to wired product surfaces. Deeper compatibility and
                analytics views will continue to expand inside those surfaces.
              </span>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: typeof Plug;
}) {
  return (
    <Card size="sm">
      <CardContent>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm text-muted-foreground">{label}</div>
            <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
            <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
          </div>
          <div className="rounded-md border bg-background p-2 text-muted-foreground">
            <Icon className="size-4" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function FlowRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Plug;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border bg-background p-3">
      <div className="flex min-w-0 items-center gap-3">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="font-medium">{label}</span>
      </div>
      <span className="truncate text-muted-foreground">{value}</span>
    </div>
  );
}
