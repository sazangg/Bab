import { ArrowLeft } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  useGetProviderApiV1ProvidersProviderIdGet,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import {
  ProviderResourcesPanel,
  ProviderRoutingPolicyField,
} from "@/features/providers/pages/ProvidersPage";

export function ProviderDetailPage() {
  const { providerId } = useParams();
  const queryClient = useQueryClient();
  const providerQuery = useGetProviderApiV1ProvidersProviderIdGet(providerId ?? "", {
    query: { enabled: Boolean(providerId) },
  });
  const updateProvider = useUpdateProviderApiV1ProvidersProviderIdPatch({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const provider = providerQuery.data?.status === 200 ? providerQuery.data.data : null;

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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={provider.name}
        description="Manage upstream credentials and model names for this provider."
        actions={
          <Button asChild variant="outline">
            <Link to="/providers">
              <ArrowLeft />
              Providers
            </Link>
          </Button>
        }
      />
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
          <ProviderSummaryFact label="Integration" value={provider.supported_integration} />
          <ProviderSummaryFact
            label="Credential routing"
            value={provider.credential_routing_policy.replaceAll("_", " ")}
          />
          <ProviderSummaryFact
            label="Request timeout"
            value={`${provider.request_timeout_seconds ?? 30}s`}
          />
          <ProviderSummaryFact
            label="Max body"
            value={
              provider.max_body_bytes
                ? `${Math.round(provider.max_body_bytes / 1024)} KB`
                : "Default"
            }
          />
          <ProviderSummaryFact
            label="Concurrency"
            value={provider.max_concurrent_requests?.toString() ?? "Default"}
          />
        </CardContent>
        <CardContent>
          <ProviderRoutingPolicyField
            value={provider.credential_routing_policy}
            disabled={updateProvider.isPending}
            onValueChange={(value) =>
              updateProvider.mutate({
                providerId: provider.id,
                data: { credential_routing_policy: value },
              })
            }
          />
        </CardContent>
      </Card>
      <ProviderResourcesPanel provider={provider} />
    </div>
  );
}

function ProviderSummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}
