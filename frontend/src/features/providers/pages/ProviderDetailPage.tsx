import { useState } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronsUpDown,
  Circle,
  KeyRound,
  Layers3,
  Pencil,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useGetProviderApiV1ProvidersProviderIdGet,
  useGetProviderImpactApiV1ProvidersProviderIdImpactGet,
  useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet,
  useListProvidersApiV1ProvidersGet,
  useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import { useGetOrganizationUsageSummaryApiV1UsageSummaryGet } from "@/shared/api/generated/usage/usage";
import { useGetSettingsApiV1SettingsGet } from "@/shared/api/generated/settings/settings";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { EditProviderSheet } from "@/features/providers/components/EditProviderSheet";
import { hasPermission } from "@/features/auth/lib/permissions";
import { ProviderResourcesPanel } from "@/features/providers/components/ProviderResourcesPanel";
import {
  formatRelativeFromNow,
  sanitizeCredentialValidationMessage,
} from "@/features/providers/lib/format";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";

export function ProviderDetailPage() {
  const { providerId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeactivateOpen, setIsDeactivateOpen] = useState(false);
  const currentUserQuery = useMeApiV1AuthMeGet();
  const settingsQuery = useGetSettingsApiV1SettingsGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const settings = settingsQuery.data?.status === 200 ? settingsQuery.data.data : null;
  const canManageProviders = hasPermission(currentUser, "providers.manage");

  const providerQuery = useGetProviderApiV1ProvidersProviderIdGet(providerId ?? "", {
    query: { enabled: Boolean(providerId) },
  });
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const allProviders = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const otherProviders = allProviders.filter((item) => item.id !== providerId);
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    providerId ?? "",
    { query: { enabled: Boolean(providerId) } },
  );
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet(
    { window: "30d", provider_id: providerId },
    { query: { enabled: Boolean(providerId) } },
  );
  const impactQuery = useGetProviderImpactApiV1ProvidersProviderIdImpactGet(providerId ?? "", {
    query: { enabled: Boolean(providerId) },
  });
  const impact = impactQuery.data?.status === 200 ? impactQuery.data.data : null;
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const topActiveCredential = [...credentials]
    .filter((credential) => credential.is_active)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())[0];
  const provider = providerQuery.data?.status === 200 ? providerQuery.data.data : null;
  const activeCredentials = credentials.filter((credential) => credential.is_active);
  const healthCounts = countByHealth(activeCredentials);
  const lastSuccess = lastSuccessfulRequestAt(credentials);
  const usageSummary = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const providerTotals = usageSummary?.totals;
  const providerRequests = providerTotals?.requests ?? 0;
  const providerFailedRequests = providerTotals?.failed_requests ?? 0;
  const providerErrorRate =
    providerRequests > 0
      ? `${Math.round((providerFailedRequests / providerRequests) * 1000) / 10}%`
      : "0%";

  const updateProvider = useUpdateProviderApiV1ProvidersProviderIdPatch({
    mutation: {
      onSuccess: async () => {
        setIsEditOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateProvider = useDeactivateProviderApiV1ProvidersProviderIdDelete({
    mutation: {
      onSuccess: async () => {
        setIsDeactivateOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const testCredential =
    useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost({
      mutation: { onSettled: async () => queryClient.invalidateQueries() },
    });

  if (!providerId) {
    return <Navigate to="/providers" replace />;
  }

  if (providerQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading provider...</p>;
  }

  if (providerQuery.isError || providerQuery.data?.status !== 200) {
    return (
      <EmptyState
        title="Provider could not be loaded"
        description="The provider detail request failed. Try again or return to the providers list."
        action={
          <Button asChild variant="outline">
            <Link to="/providers">Back to providers</Link>
          </Button>
        }
      />
    );
  }

  if (!provider) {
    return (
      <EmptyState
        title="Provider not found"
        description="This provider no longer exists or is not available to this account."
        action={
          <Button asChild variant="outline">
            <Link to="/providers">Back to providers</Link>
          </Button>
        }
      />
    );
  }

  const handleEnabledChange = (checked: boolean) => {
    if (checked) {
      updateProvider.mutate({
        providerId: provider.id,
        data: { is_active: true },
      });
    } else {
      setIsDeactivateOpen(true);
    }
  };

  const handleTestConnectivity = () => {
    if (!topActiveCredential) {
      toast.error("Add an active credential before testing connectivity.");
      return;
    }
    testCredential.mutate(
      { providerId: provider.id, providerCredentialId: topActiveCredential.id },
      {
        onSuccess: (response) => {
          const valid = response.status === 200 && response.data.health_status === "valid";
          if (valid) {
            toast.success(`Connectivity OK using credential "${topActiveCredential.name}".`);
          } else {
            toast.error(`Connectivity test failed using credential "${topActiveCredential.name}".`);
          }
        },
        onError: () => {
          toast.error("Connectivity test failed. Check provider credentials and base URL.");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={provider.name}
        description={provider.description ?? "Manage credentials, models, and routing policies."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {otherProviders.length > 0 ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm">
                    Switch
                    <ChevronsUpDown />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>Switch provider</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {otherProviders.map((item) => (
                    <DropdownMenuItem
                      key={item.id}
                      onSelect={() => navigate(`/providers/${item.id}`)}
                    >
                      <span className="truncate">{item.name}</span>
                      {!item.is_active ? (
                        <StatusBadge variant="inactive">Disabled</StatusBadge>
                      ) : null}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            <Button
              variant="outline"
              onClick={handleTestConnectivity}
              disabled={!topActiveCredential || testCredential.isPending}
              title={
                topActiveCredential
                  ? "Probes the first active provider credential."
                  : "Add an active credential first."
              }
            >
              <Activity />
              {testCredential.isPending ? "Testing..." : "Test connectivity"}
            </Button>
            {canManageProviders ? (
              <>
                <Button variant="outline" onClick={() => setIsEditOpen(true)}>
                  <Pencil />
                  Settings
                </Button>
                <Label
                  className="ml-1 flex items-center gap-2 text-xs font-medium text-muted-foreground"
                  htmlFor="provider-enabled-switch"
                >
                  Enabled
                  <Switch
                    id="provider-enabled-switch"
                    checked={provider.is_active}
                    disabled={updateProvider.isPending || deactivateProvider.isPending}
                    onCheckedChange={handleEnabledChange}
                  />
                </Label>
              </>
            ) : null}
          </div>
        }
      />

      <div
        className={cn(
          "flex flex-col gap-4 rounded-md border p-4 md:flex-row md:items-center md:justify-between",
          provider.readiness?.status === "ready"
            ? "border-emerald-500/30 bg-emerald-500/5"
            : "border-amber-500/30 bg-amber-500/5",
        )}
      >
        <div className="flex items-start gap-3">
          {provider.readiness?.status === "ready" ? (
            <CheckCircle2 className="mt-0.5 size-5 text-emerald-600" />
          ) : (
            <Circle className="mt-0.5 size-5 text-amber-600" />
          )}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{readinessBadge(provider.readiness?.status).label}</p>
              <StatusBadge variant={provider.is_active ? "active" : "inactive"}>
                {provider.is_active ? "Enabled" : "Disabled"}
              </StatusBadge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{provider.readiness?.message}</p>
          </div>
        </div>
        {canManageProviders ? (
          <ProviderNextAction
            provider={provider}
            onAddCredential={() =>
              navigate(`/providers/${provider.id}?tab=credentials&action=add-credential`)
            }
            onOpenPools={() => navigate(`/providers/${provider.id}?tab=pools`)}
            onOpenModels={() => navigate(`/providers/${provider.id}?tab=models`)}
          />
        ) : null}
      </div>

      <ProviderResourcesPanel provider={provider} canManage={canManageProviders} />

      <Card>
        <CardHeader>
          <CardTitle>Provider metadata</CardTitle>
          <CardDescription>{provider.base_url}</CardDescription>
          <CardAction>
            <StatusBadge variant={provider.is_active ? "active" : "inactive"}>
              {provider.is_active ? "Active" : "Disabled"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-x-6 gap-y-4 md:grid-cols-4">
          <Fact
            label="Integration"
            value={formatIntegrationLabel(provider.supported_integration)}
          />
          <Fact label="Adapter" value={formatAdapterLabel(provider)} />
          <Fact label="Active credentials" value={`${activeCredentials.length}`} />
          <Fact
            label="Last successful request"
            value={lastSuccess ? formatRelativeFromNow(lastSuccess) : "Never"}
          />
          <Fact
            label="Request timeout"
            value={
              provider.request_timeout_seconds == null
                ? `Inherited (${settings?.default_request_timeout_seconds ?? 30}s)`
                : `${provider.request_timeout_seconds}s`
            }
          />
          <Fact
            label="Max body"
            value={
              provider.max_body_bytes
                ? `${Math.round(provider.max_body_bytes / 1024)} KB`
                : `Inherited (${Math.round((settings?.default_max_body_bytes ?? 0) / 1024).toLocaleString()} KB)`
            }
          />
          <Fact
            label="Model sync"
            value={
              provider.model_sync_mode ??
              `Inherited (${settings?.default_model_sync_mode ?? "merge"})`
            }
          />
          <Fact
            label="Retry policy"
            value={formatProviderRetry(provider.retry_policy, settings?.default_retry_count ?? 0)}
          />
          <Fact
            label="Concurrency"
            value={provider.max_concurrent_requests?.toString() ?? "No cap"}
          />
          <div className="flex flex-col gap-1 md:col-span-2">
            <p className="text-xs text-muted-foreground">Credential health</p>
            {activeCredentials.length === 0 ? (
              <p className="text-sm text-muted-foreground">Add a credential to start routing.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {(Object.keys(healthCounts) as Array<keyof typeof healthCounts>).map((key) =>
                  healthCounts[key] > 0 ? (
                    <StatusBadge key={key} variant={healthLabels[key]?.variant ?? "muted"}>
                      {healthCounts[key]} {healthLabels[key]?.label ?? key}
                    </StatusBadge>
                  ) : null,
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1 md:col-span-4">
            <p className="text-xs text-muted-foreground">Provider capabilities</p>
            <div className="flex flex-wrap gap-1.5">
              {providerCapabilityLabels(provider.integration_capabilities).length > 0 ? (
                providerCapabilityLabels(provider.integration_capabilities).map((capability) => (
                  <StatusBadge key={capability} variant="muted">
                    {capability}
                  </StatusBadge>
                ))
              ) : (
                <span className="text-sm text-muted-foreground">
                  No runtime capabilities enabled yet.
                </span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Policy dependencies</CardTitle>
          <CardDescription>
            Active governance resources that reference this provider.
          </CardDescription>
          <CardAction>
            <StatusBadge variant={impact?.access_policies?.length ? "active" : "muted"}>
              {impact?.access_policies?.length ?? 0} routes
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-2">
          {impactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading dependencies...</p>
          ) : impact?.access_policies?.length ? (
            <div className="flex flex-wrap gap-2">
              {impact.access_policies.map((policy) => (
                <Button key={policy.route_id} asChild size="sm" variant="outline">
                  <Link to={`/policies?policy=${policy.id}`}>{policy.name}</Link>
                </Button>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No active access policy routes reference this provider.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Readiness chain</CardTitle>
          <CardDescription>
            A provider is routable only when every step below is ready.
          </CardDescription>
          <CardAction>
            <StatusBadge variant={readinessBadge(provider.readiness?.status).variant}>
              {readinessBadge(provider.readiness?.status).label}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{provider.readiness?.message}</p>
          <div className="grid gap-3 md:grid-cols-5">
            <ReadinessStep
              label="Provider enabled"
              ready={Boolean(provider.readiness?.has_active_provider)}
            />
            <ReadinessStep
              label="Active credential"
              ready={Boolean(provider.readiness?.has_active_credential)}
            />
            <ReadinessStep
              label="Active pool"
              ready={Boolean(provider.readiness?.has_active_pool)}
            />
            <ReadinessStep
              label="Credential in pool"
              ready={Boolean(provider.readiness?.has_active_pool_credential)}
            />
            <ReadinessStep
              label="Active models"
              ready={Boolean(provider.readiness?.has_active_model)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operational state</CardTitle>
          <CardDescription>
            Runtime routing controls and recent circuit breaker observations.
          </CardDescription>
          <CardAction>
            <StatusBadge
              variant={provider.operational_state?.circuit_state === "open" ? "error" : "active"}
            >
              Circuit {provider.operational_state?.circuit_state ?? "closed"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-x-6 gap-y-4 md:grid-cols-4">
          <Fact
            label="Circuit breaker"
            value={provider.operational_state?.circuit_breaker_enabled ? "Enabled" : "Disabled"}
          />
          <Fact
            label="Recent failures"
            value={`${provider.operational_state?.recent_circuit_failures ?? 0}`}
          />
          <Fact
            label="Recent successes"
            value={`${provider.operational_state?.recent_circuit_successes ?? 0}`}
          />
          <Fact
            label="Open until"
            value={
              provider.operational_state?.circuit_open_until
                ? formatRelativeFromNow(new Date(provider.operational_state.circuit_open_until))
                : "-"
            }
          />
          <Fact
            label="Last upstream failure"
            value={lastCredentialFailure(activeCredentials) ?? "-"}
          />
        </CardContent>
      </Card>

      <EditProviderSheet
        provider={isEditOpen ? provider : null}
        onClose={() => setIsEditOpen(false)}
        isPending={updateProvider.isPending}
        onSubmit={(data) => updateProvider.mutate({ providerId: provider.id, data })}
      />

      <Card>
        <CardHeader>
          <CardTitle>Usage metrics</CardTitle>
          <CardDescription>Provider usage across the last 30 days.</CardDescription>
          <CardAction>
            <StatusBadge variant={providerRequests > 0 ? "active" : "muted"}>
              {usageQuery.isPending ? "Loading" : providerRequests > 0 ? "Observed" : "No usage"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact label="Requests" value={providerRequests.toLocaleString()} />
          <Fact label="Error rate" value={providerErrorRate} />
          <Fact
            label="Latency"
            value={
              providerTotals?.average_latency_ms == null
                ? "-"
                : `${providerTotals.average_latency_ms}ms`
            }
          />
          <Fact label="Known spend" value={formatCents(providerTotals?.cost_cents ?? 0)} />
        </CardContent>
      </Card>

      <UsageRecordsDrilldown
        title="Provider usage records"
        filters={{ provider_id: provider.id }}
      />

      <Dialog open={isDeactivateOpen} onOpenChange={setIsDeactivateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate {provider.name}?</DialogTitle>
            <DialogDescription>
              Requests routed to this provider will start failing. Credentials and project access
              rules stay intact, and you can re-enable from this same toggle later.
            </DialogDescription>
          </DialogHeader>
          <ProviderImpactWarning impact={impact} isLoading={impactQuery.isPending} />
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={deactivateProvider.isPending}
              onClick={() => deactivateProvider.mutate({ providerId: provider.id })}
            >
              {deactivateProvider.isPending ? "Deactivating..." : "Deactivate"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProviderNextAction({
  provider,
  onAddCredential,
  onOpenPools,
  onOpenModels,
}: {
  provider: {
    readiness?: {
      status?: string;
      has_active_credential?: boolean;
      has_active_pool?: boolean;
      has_active_pool_credential?: boolean;
      has_active_model?: boolean;
    };
  };
  onAddCredential: () => void;
  onOpenPools: () => void;
  onOpenModels: () => void;
}) {
  if (!provider.readiness?.has_active_credential) {
    return (
      <Button onClick={onAddCredential}>
        <KeyRound />
        Add credential
      </Button>
    );
  }
  if (!provider.readiness?.has_active_pool || !provider.readiness?.has_active_pool_credential) {
    return (
      <Button onClick={onOpenPools}>
        <Layers3 />
        Configure pool
      </Button>
    );
  }
  if (!provider.readiness?.has_active_model) {
    return (
      <Button onClick={onOpenModels}>
        <Layers3 />
        Add or sync models
      </Button>
    );
  }
  return (
    <Button asChild>
      <Link to="/playground">Open playground</Link>
    </Button>
  );
}

function Fact({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("truncate text-sm font-medium", muted && "text-muted-foreground/70")}>
        {value}
      </p>
    </div>
  );
}

function ProviderImpactWarning({
  impact,
  isLoading,
}: {
  impact: import("@/shared/api/generated/schemas").ProviderImpactResponse | null;
  isLoading: boolean;
}) {
  if (isLoading) return <p className="text-sm text-muted-foreground">Checking impact...</p>;
  if (!impact) return null;
  return (
    <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
      <p className="font-medium">Resources affected</p>
      <p className="mt-1 text-muted-foreground">
        {impact.access_policies?.length ?? 0} access routes, {impact.active_limit_rule_count ?? 0}{" "}
        limit rules, {impact.active_pool_count ?? 0} pools, and {impact.active_model_count ?? 0}{" "}
        models reference this provider.
      </p>
      <p className="mt-1 text-muted-foreground">
        Last 30 days: {(impact.recent_request_count ?? 0).toLocaleString()} requests and{" "}
        {formatCents(impact.recent_cost_cents ?? 0)} estimated spend.
      </p>
      {impact.access_policies?.length ? (
        <p className="mt-2">
          Policies: {impact.access_policies.map((item) => item.name).join(", ")}
        </p>
      ) : null}
    </div>
  );
}

function formatProviderRetry(value: unknown, defaultRetryCount: number) {
  if (!value || typeof value !== "object") {
    return defaultRetryCount > 0
      ? `Inherited (${defaultRetryCount + 1} attempts)`
      : "Inherited (no retries)";
  }
  const policy = value as { enabled?: boolean; max_attempts?: number };
  if (!policy.enabled) return "Disabled override";
  return `${policy.max_attempts ?? 1} attempts`;
}

function ReadinessStep({ label, ready }: { label: string; ready: boolean }) {
  const Icon = ready ? CheckCircle2 : Circle;
  return (
    <div className="flex items-center gap-2 rounded-md border bg-muted/20 p-3">
      <Icon
        className={cn("size-4 shrink-0", ready ? "text-emerald-600" : "text-muted-foreground")}
      />
      <span className={cn("text-sm font-medium", !ready && "text-muted-foreground")}>{label}</span>
    </div>
  );
}

type HealthVariant = "active" | "inactive" | "error" | "muted";

const healthLabels: Record<string, { label: string; variant: HealthVariant }> = {
  valid: { label: "Valid", variant: "active" },
  unchecked: { label: "Unchecked", variant: "muted" },
  invalid: { label: "Invalid", variant: "error" },
  degraded: { label: "Degraded", variant: "error" },
};

function readinessBadge(status: string | undefined) {
  const states: Record<
    string,
    { label: string; variant: "active" | "inactive" | "error" | "expired" }
  > = {
    ready: { label: "Ready", variant: "active" },
    degraded: { label: "Degraded", variant: "error" },
    disabled: { label: "Disabled", variant: "inactive" },
    needs_credential: { label: "Needs credential", variant: "expired" },
    needs_pool: { label: "Needs pool", variant: "expired" },
    needs_model_sync: { label: "Needs model sync", variant: "expired" },
  };
  return states[status ?? ""] ?? { label: "Incomplete", variant: "expired" as const };
}

function providerCapabilityLabels(capabilities: Record<string, boolean> | undefined) {
  const labels: Record<string, string> = {
    openai_compatible_chat: "OpenAI-compatible chat",
    openai_compatible_models_list: "OpenAI-compatible models list",
    openai_compatible_responses: "Responses compatibility",
    openai_compatible_completions: "Completions compatibility",
    streaming: "Streaming",
    native_anthropic_messages: "Native Anthropic Messages",
    native_anthropic_models_list: "Native Anthropic model list",
    embeddings: "Embeddings",
  };
  return Object.entries(capabilities ?? {})
    .filter(([, enabled]) => enabled)
    .map(([key]) => labels[key] ?? key);
}

function formatAdapterLabel(provider: { adapter_type: string; supported_integration: string }) {
  if (provider.supported_integration === "anthropic_messages") {
    return "Native Anthropic messages";
  }
  if (provider.adapter_type === "openai_compat") {
    return "OpenAI-compatible";
  }
  return provider.adapter_type;
}

function formatIntegrationLabel(value: string) {
  if (value === "openai_compatible_default") return "Built-in OpenAI-compatible";
  if (value === "openai_compatible") return "Custom OpenAI-compatible";
  if (value === "anthropic_messages") return "Native Anthropic Messages";
  return value.replaceAll("_", " ");
}

function countByHealth(credentials: { health_status: string }[]) {
  const counts: Record<string, number> = {
    valid: 0,
    unchecked: 0,
    invalid: 0,
    degraded: 0,
  };
  for (const credential of credentials) {
    const status = credential.health_status in counts ? credential.health_status : "unchecked";
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

function lastSuccessfulRequestAt(
  credentials: { last_successful_request_at: string | null }[],
): Date | null {
  let latest: Date | null = null;
  for (const credential of credentials) {
    if (!credential.last_successful_request_at) continue;
    const parsed = new Date(credential.last_successful_request_at);
    if (Number.isNaN(parsed.getTime())) continue;
    if (!latest || parsed > latest) latest = parsed;
  }
  return latest;
}

function lastCredentialFailure(
  credentials: {
    failure_message?: string | null;
    last_failure_at?: string | null;
    last_validation_error: string | null;
    health_status: string;
  }[],
) {
  const failed = [...credentials]
    .filter((credential) => credential.failure_message || credential.last_validation_error)
    .sort((a, b) => {
      const aTime = a.last_failure_at ? new Date(a.last_failure_at).getTime() : 0;
      const bTime = b.last_failure_at ? new Date(b.last_failure_at).getTime() : 0;
      return bTime - aTime;
    })[0];
  if (!failed) return null;
  return (
    sanitizeCredentialValidationMessage(failed.failure_message ?? failed.last_validation_error) ??
    "Credential validation failed."
  );
}

function formatCents(value: number) {
  return `$${(value / 100).toLocaleString()}`;
}
