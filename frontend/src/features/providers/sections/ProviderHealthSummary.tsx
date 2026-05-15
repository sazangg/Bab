import { Card, CardContent } from "@/components/ui/card";
import { useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet } from "@/shared/api/generated/providers/providers";
import type { ProviderCredentialResponse, ProviderResponse } from "@/shared/api/generated/schemas";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { formatRelativeFromNow } from "../lib/format";

type HealthVariant = "active" | "inactive" | "error" | "muted";

const healthLabels: Record<string, { label: string; variant: HealthVariant }> = {
  valid: { label: "Valid", variant: "active" },
  unchecked: { label: "Unchecked", variant: "muted" },
  invalid: { label: "Invalid", variant: "error" },
  degraded: { label: "Degraded", variant: "error" },
};

export function ProviderHealthSummary({ provider }: { provider: ProviderResponse }) {
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    provider.id,
  );

  if (credentialsQuery.isPending) {
    return (
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 py-3">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-5 w-40" />
        </CardContent>
      </Card>
    );
  }

  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const active = credentials.filter((credential) => credential.is_active);
  const counts = countByHealth(active);
  const lastSuccess = lastSuccessfulRequestAt(credentials);

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 py-3">
        <Stat label="Active credentials" value={String(active.length)} />
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Health</span>
          {active.length === 0 ? (
            <span className="text-xs text-muted-foreground">
              Add a credential to start routing.
            </span>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              {(Object.keys(counts) as Array<keyof typeof counts>).map((key) =>
                counts[key] > 0 ? (
                  <StatusBadge key={key} variant={healthLabels[key]?.variant ?? "muted"}>
                    {counts[key]} {healthLabels[key]?.label ?? key}
                  </StatusBadge>
                ) : null,
              )}
            </div>
          )}
        </div>
        <Stat
          label="Last successful request"
          value={lastSuccess ? formatRelativeFromNow(lastSuccess) : "Never"}
        />
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}

function countByHealth(credentials: ProviderCredentialResponse[]) {
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

function lastSuccessfulRequestAt(credentials: ProviderCredentialResponse[]): Date | null {
  let latest: Date | null = null;
  for (const credential of credentials) {
    if (!credential.last_successful_request_at) continue;
    const parsed = new Date(credential.last_successful_request_at);
    if (Number.isNaN(parsed.getTime())) continue;
    if (!latest || parsed > latest) latest = parsed;
  }
  return latest;
}
