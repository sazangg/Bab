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
import { ProviderHealthSummary } from "@/features/providers/sections/ProviderHealthSummary";

const routingPolicyLabels: Record<string, string> = {
  priority: "Priority",
  round_robin: "Round robin",
  least_recently_used: "Least recently used",
  health_based: "Health based",
  weighted: "Weighted",
  fallback: "Fallback",
};

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
    .sort((a, b) => a.priority - b.priority)[0];
  const provider = providerQuery.data?.status === 200 ? providerQuery.data.data : null;

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
                  ? "Probes the highest-priority active credential."
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

      <ProviderHealthSummary provider={provider} />

      <Card>
        <CardHeader>
          <CardTitle>Provider summary</CardTitle>
          <CardDescription>{provider.base_url}</CardDescription>
          <CardAction>
            <StatusBadge variant={provider.is_active ? "active" : "inactive"}>
              {provider.is_active ? "Active" : "Disabled"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact label="Integration" value={provider.supported_integration} />
          <Fact label="Adapter" value={provider.adapter_type} />
          <Fact
            label="Credential routing"
            value={formatRoutingPolicy(provider.credential_routing_policy)}
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
            Provider and model analytics will appear here once request logging captures provider,
            credential, and model dimensions.
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

function formatRoutingPolicy(value: string) {
  return routingPolicyLabels[value] ?? value.replaceAll("_", " ");
}
