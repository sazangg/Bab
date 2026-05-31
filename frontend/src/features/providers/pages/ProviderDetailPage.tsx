import { useState } from "react";
import { Activity, CheckCircle2, ChevronsUpDown, Circle, Pencil } from "lucide-react";
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
import { formatRelativeFromNow } from "@/features/providers/lib/format";
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
          <div className="flex items-center gap-2">
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
          <Fact label="Integration" value={provider.supported_integration} />
          <Fact label="Adapter" value={provider.adapter_type} />
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Readiness chain</CardTitle>
          <CardDescription>
            A provider is routable only when every step below is ready.
          </CardDescription>
          <CardAction>
            <StatusBadge variant={provider.readiness?.is_ready ? "active" : "expired"}>
              {provider.readiness?.is_ready ? "Ready" : "Incomplete"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-5">
          <ReadinessStep
            label="Provider enabled"
            ready={Boolean(provider.readiness?.has_active_provider)}
          />
          <ReadinessStep
            label="Active credential"
            ready={Boolean(provider.readiness?.has_active_credential)}
          />
          <ReadinessStep label="Active pool" ready={Boolean(provider.readiness?.has_active_pool)} />
          <ReadinessStep
            label="Credential in pool"
            ready={Boolean(provider.readiness?.has_active_pool_credential)}
          />
          <ReadinessStep
            label="Active models"
            ready={Boolean(provider.readiness?.has_active_model)}
          />
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
            label="Fallback policy"
            value={provider.operational_state?.fallback_enabled ? "Enabled" : "Disabled"}
          />
          <Fact
            label="Fallback providers"
            value={`${provider.operational_state?.fallback_provider_count ?? 0}`}
          />
          <Fact
            label="Fallback statuses"
            value={
              provider.operational_state?.fallback_trigger_statuses?.length
                ? provider.operational_state.fallback_trigger_statuses.join(", ")
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
          <Fact label="Estimated spend" value={formatCents(providerTotals?.cost_cents ?? 0)} />
        </CardContent>
      </Card>

      <UsageRecordsDrilldown
        title="Provider usage records"
        filters={{ provider_id: provider.id }}
      />

      <ProviderResourcesPanel provider={provider} />

      <Dialog open={isDeactivateOpen} onOpenChange={setIsDeactivateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate {provider.name}?</DialogTitle>
            <DialogDescription>
              Requests routed to this provider will start failing. Credentials and project access
              rules stay intact, and you can re-enable from this same toggle later.
            </DialogDescription>
          </DialogHeader>
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
  credentials: { last_validation_error: string | null; health_status: string }[],
) {
  const failed = credentials.find((credential) => credential.last_validation_error);
  if (!failed) return null;
  return failed.last_validation_error;
}

function formatCents(value: number) {
  return `$${(value / 100).toLocaleString()}`;
}
