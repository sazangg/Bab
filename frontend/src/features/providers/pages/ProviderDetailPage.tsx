import { useState } from "react";
import { Activity, ChevronsUpDown, Pencil } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { EditProviderSheet } from "@/features/providers/components/EditProviderSheet";
import { ProviderResourcesPanel } from "@/features/providers/components/ProviderResourcesPanel";
import { formatRelativeFromNow } from "@/features/providers/lib/format";

export function ProviderDetailPage() {
  const { providerId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeactivateOpen, setIsDeactivateOpen] = useState(false);

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
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const topActiveCredential = [...credentials]
    .filter((credential) => credential.is_active)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())[0];
  const provider = providerQuery.data?.status === 200 ? providerQuery.data.data : null;
  const activeCredentials = credentials.filter((credential) => credential.is_active);
  const healthCounts = countByHealth(activeCredentials);
  const lastSuccess = lastSuccessfulRequestAt(credentials);

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
          <Fact label="Request timeout" value={`${provider.request_timeout_seconds ?? 30}s`} />
          <Fact
            label="Max body"
            value={
              provider.max_body_bytes
                ? `${Math.round(provider.max_body_bytes / 1024)} KB`
                : "Unlimited"
            }
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

      <EditProviderSheet
        provider={isEditOpen ? provider : null}
        onClose={() => setIsEditOpen(false)}
        isPending={updateProvider.isPending}
        onSubmit={(data) => updateProvider.mutate({ providerId: provider.id, data })}
      />

      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-muted-foreground">Usage metrics</CardTitle>
          <CardDescription>
            Provider and model metrics will appear here once usage records are exposed for querying.
          </CardDescription>
          <CardAction>
            <StatusBadge variant="muted">Coming soon</StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact label="Requests" value="—" muted />
          <Fact label="Error rate" value="—" muted />
          <Fact label="Latency" value="—" muted />
          <Fact label="Estimated spend" value="—" muted />
        </CardContent>
      </Card>

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
