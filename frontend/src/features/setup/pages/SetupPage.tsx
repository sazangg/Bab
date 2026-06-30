import { AlertTriangle, ArrowRight, CheckCircle2, Circle, ListChecks } from "lucide-react";
import { Link } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useListGatewayRequestsApiV1GatewayHistoryRequestsGet } from "@/shared/api/generated/gateway-history/gateway-history";
import { useListPoliciesApiV1GuardrailsPoliciesGet } from "@/shared/api/generated/guardrails/guardrails";
import {
  useListAccessPoliciesApiV1PoliciesAccessGet,
  useListLimitPoliciesApiV1PoliciesLimitsGet,
} from "@/shared/api/generated/policies/policies";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { useListVirtualKeyInventoryApiV1VirtualKeysGet } from "@/shared/api/generated/virtual-keys/virtual-keys";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { buildSetupStatus, type SetupStepState } from "@/features/setup/lib/setup-status";

export function SetupPage() {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const keysQuery = useListVirtualKeyInventoryApiV1VirtualKeysGet({ limit: 100 });
  const gatewayRequestsQuery = useListGatewayRequestsApiV1GatewayHistoryRequestsGet({
    window: "lifetime",
    limit: 1,
  });
  const accessPoliciesQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const limitPoliciesQuery = useListLimitPoliciesApiV1PoliciesLimitsGet();
  const guardrailPoliciesQuery = useListPoliciesApiV1GuardrailsPoliciesGet();

  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const keysPage = keysQuery.data?.status === 200 ? keysQuery.data.data : null;
  const gatewayRequests =
    gatewayRequestsQuery.data?.status === 200 ? gatewayRequestsQuery.data.data.items : [];
  const accessPolicies =
    accessPoliciesQuery.data?.status === 200 ? accessPoliciesQuery.data.data : [];
  const limitPolicies = limitPoliciesQuery.data?.status === 200 ? limitPoliciesQuery.data.data : [];
  const guardrailPolicies =
    guardrailPoliciesQuery.data?.status === 200 ? guardrailPoliciesQuery.data.data : [];

  const readyProviders = providers.filter((provider) => provider.readiness?.is_ready);
  const usableKeys = (keysPage?.items ?? []).filter((key) => key.is_usable);
  const setup = buildSetupStatus({
    providersCount: providers.length,
    readyProvidersCount: readyProviders.length,
    teamsCount: teams.length,
    projectsCount: projects.length,
    usableVirtualKeysCount: usableKeys.length,
    gatewayRequestsCount: gatewayRequests.length,
    accessPoliciesCount: accessPolicies.length,
    limitPoliciesCount: limitPolicies.length,
    guardrailPoliciesCount: guardrailPolicies.length,
  });
  const requiredQueries = [
    providersQuery,
    teamsQuery,
    projectsQuery,
    keysQuery,
    gatewayRequestsQuery,
  ];
  const isLoading = requiredQueries.some((query) => query.isPending);
  const hasPartialError = [
    ...requiredQueries,
    accessPoliciesQuery,
    limitPoliciesQuery,
    guardrailPoliciesQuery,
  ].some((query) => query.isError);
  const nextStep = setup.nextRequiredStep;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Setup"
        description="Track the readiness chain for the first successful gateway request."
      />

      {hasPartialError ? (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Some setup data could not be loaded</AlertTitle>
          <AlertDescription>
            Known setup state is still shown. Refresh after checking the failing surface.
          </AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Loading setup status...
          </CardContent>
        </Card>
      ) : (
        <>
          <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
            <Card>
              <CardHeader>
                <CardTitle>Readiness</CardTitle>
                <CardDescription>
                  {setup.completedRequiredCount} of {setup.totalRequiredCount} required steps
                  complete.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold">
                  {Math.round(
                    (setup.completedRequiredCount / setup.totalRequiredCount) * 100,
                  ).toLocaleString()}
                  %
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {setup.isComplete
                    ? "The gateway is ready for normal operation."
                    : "Complete the next required step to keep setup moving."}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{nextStep ? "Next step" : "Setup complete"}</CardTitle>
                <CardDescription>
                  {nextStep
                    ? "This is the first blocker in the readiness chain."
                    : "Continue with daily operations or review request history."}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium">{nextStep?.label ?? "Review gateway history"}</div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {nextStep?.description ??
                      "Inspect request history and usage once traffic is flowing."}
                  </p>
                </div>
                <Button asChild>
                  <Link to={nextStep?.to ?? "/gateway-history"}>
                    {nextStep?.actionLabel ?? "Open gateway history"}
                    <ArrowRight data-icon="inline-end" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-3">
            {setup.requiredSteps.map((step) => (
              <SetupStepRow key={step.id} step={step} />
            ))}
          </section>

          <section>
            <h2 className="mb-2 text-sm font-medium">Optional control layer</h2>
            {setup.steps
              .filter((step) => step.optional)
              .map((step) => (
                <SetupStepRow key={step.id} step={step} />
              ))}
          </section>
        </>
      )}
    </div>
  );
}

function SetupStepRow({ step }: { step: SetupStepState }) {
  const Icon = step.complete ? CheckCircle2 : Circle;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-card p-4">
      <div className="flex min-w-0 items-start gap-3">
        <Icon
          className={step.complete ? "mt-0.5 size-5 text-success" : "mt-0.5 size-5 text-muted-foreground"}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">{step.label}</h2>
            <StatusBadge variant={step.complete ? "active" : "muted"}>
              {step.complete ? "Complete" : step.optional ? "Optional" : "To do"}
            </StatusBadge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
        </div>
      </div>
      <Button asChild variant={step.complete ? "outline" : "default"} size="sm">
        <Link to={step.to}>
          <ListChecks data-icon="inline-start" />
          {step.actionLabel}
        </Link>
      </Button>
    </div>
  );
}
