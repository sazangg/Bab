import { Activity, Boxes, BrainCircuit, Clock, KeyRound, WalletCards } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { OrganizationUsageSummary, UsageBreakdownRow } from "@/shared/api/generated/schemas";

export function EntityUsageCard({
  title = "Usage",
  description = "Aggregate gateway usage across this workspace scope.",
  usage,
  isLoading,
}: {
  title?: string;
  description?: string;
  usage: OrganizationUsageSummary | null | undefined;
  isLoading: boolean;
}) {
  const totals = usage?.totals;
  const requests = totals?.requests ?? 0;
  const failed = totals?.failed_requests ?? 0;
  const errorRate = requests > 0 ? `${Math.round((failed / requests) * 1000) / 10}%` : "0%";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading usage...</p>
        ) : requests === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center">
            <p className="text-sm font-medium">No usage recorded</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Usage appears here after virtual keys in this scope receive proxy traffic.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-5">
              <UsageFact icon={Activity} label="Requests" value={requests.toLocaleString()} />
              <UsageFact
                icon={BrainCircuit}
                label="Tokens"
                value={(totals?.total_tokens ?? 0).toLocaleString()}
              />
              <UsageFact icon={WalletCards} label="Spend" value={formatCents(totals?.cost_cents)} />
              <UsageFact icon={Boxes} label="Errors" value={errorRate} />
              <UsageFact
                icon={Clock}
                label="Latency"
                value={totals?.average_latency_ms == null ? "-" : `${totals.average_latency_ms}ms`}
              />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <Breakdown title="Virtual keys" rows={usage?.by_virtual_key ?? []} icon={KeyRound} />
              <Breakdown title="Models" rows={usage?.by_model ?? []} icon={BrainCircuit} />
              <Breakdown title="Providers" rows={usage?.by_provider ?? []} icon={Activity} />
              <Breakdown title="Pools" rows={usage?.by_pool ?? []} icon={Boxes} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function UsageFact({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function Breakdown({
  title,
  rows,
  icon: Icon,
}: {
  title: string;
  rows: UsageBreakdownRow[];
  icon: typeof Activity;
}) {
  const maxRequests = Math.max(...rows.map((row) => row.requests ?? 0), 0);
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No usage</p>
      ) : (
        <div className="space-y-2">
          {rows.slice(0, 5).map((row) => (
            <div key={row.id} className="space-y-1">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">{row.label}</span>
                <span className="shrink-0 text-muted-foreground">
                  {(row.requests ?? 0).toLocaleString()} req
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-background">
                <div
                  className="h-full rounded-full bg-primary/70"
                  style={{
                    width: `${maxRequests ? Math.max(4, ((row.requests ?? 0) / maxRequests) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatCents(value: number | null | undefined) {
  return `$${((value ?? 0) / 100).toLocaleString()}`;
}
