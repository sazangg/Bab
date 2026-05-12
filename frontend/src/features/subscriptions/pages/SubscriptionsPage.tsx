import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListSubscriptionsApiV1SubscriptionsGet } from "@/shared/api/generated/subscriptions/subscriptions";
import { PageHeader } from "@/shared/components/PageHeader";
import { SubscriptionsPanel } from "@/features/providers/pages/ProvidersPage";

export function SubscriptionsPage() {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const subscriptionsQuery = useListSubscriptionsApiV1SubscriptionsGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const subscriptions =
    subscriptionsQuery.data?.status === 200 ? subscriptionsQuery.data.data : [];

  return (
    <>
      <PageHeader
        title="Subscriptions"
        description="Bundle provider keys into reusable access packages for projects."
      />
      <SubscriptionsPanel providers={providers} subscriptions={subscriptions} />
    </>
  );
}
