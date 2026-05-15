import { useState } from "react";
import { ArrowLeft, Pencil } from "lucide-react";
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
import { EditProviderSheet, ProviderResourcesPanel } from "@/features/providers/pages/ProvidersPage";

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
  const [isEditOpen, setIsEditOpen] = useState(false);
  const queryClient = useQueryClient();
  const providerQuery = useGetProviderApiV1ProvidersProviderIdGet(providerId ?? "", {
    query: { enabled: Boolean(providerId) },
  });
  const updateProvider = useUpdateProviderApiV1ProvidersProviderIdPatch({
    mutation: {
      onSuccess: async () => {
        setIsEditOpen(false);
        await queryClient.invalidateQueries();
      },
    },
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
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setIsEditOpen(true)}>
              <Pencil />
              Edit provider
            </Button>
            <Button asChild variant="outline">
              <Link to="/providers">
                <ArrowLeft />
                Providers
              </Link>
            </Button>
          </div>
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
            value={formatRoutingPolicy(provider.credential_routing_policy)}
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
      </Card>
      <EditProviderSheet
        provider={isEditOpen ? provider : null}
        onClose={() => setIsEditOpen(false)}
        isPending={updateProvider.isPending}
        onSubmit={(values) =>
          updateProvider.mutate({
            providerId: provider.id,
            data: {
              name: values.name,
              ...(values.slug ? { slug: values.slug } : {}),
              base_url: values.base_url,
              credential_routing_policy: values.credential_routing_policy,
            },
          })
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>Usage metrics</CardTitle>
          <CardDescription>
            Provider and model analytics will appear here once request logging captures provider,
            credential, and model offering dimensions.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <ProviderSummaryFact label="Requests" value="Pending" />
          <ProviderSummaryFact label="Error rate" value="Pending" />
          <ProviderSummaryFact label="Latency" value="Pending" />
          <ProviderSummaryFact label="Estimated spend" value="Pending" />
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

function formatRoutingPolicy(value: string) {
  return routingPolicyLabels[value] ?? value.replaceAll("_", " ");
}
