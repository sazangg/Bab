import { ArrowLeft } from "lucide-react";
import { Link, Navigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { ProviderResourcesPanel } from "@/features/providers/pages/ProvidersPage";

export function ProviderDetailPage() {
  const { providerId } = useParams();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const provider = providers.find((item) => item.id === providerId);

  if (!providerId) {
    return <Navigate to="/providers" replace />;
  }

  if (providersQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading provider...</p>;
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
    <>
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
      <ProviderResourcesPanel provider={provider} />
    </>
  );
}
