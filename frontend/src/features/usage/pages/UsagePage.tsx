import { AlertTriangle, ChartNoAxesCombined, Clock, Timer, WalletCards } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGetOrganizationUsageSummaryApiV1UsageSummaryGet } from "@/shared/api/generated/usage/usage";
import type { ActivityEventResponse, UsageBreakdownRow } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

type UsageWindow = "24h" | "7d" | "30d" | "lifetime";

export function UsagePage() {
  const [window, setWindow] = useState<UsageWindow>("30d");
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet({ window });
  const summary = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const totals = summary?.totals;
  const requests = totals?.requests ?? 0;
  const failed = totals?.failed_requests ?? 0;
  const errorRate = requests > 0 ? `${Math.round((failed / requests) * 1000) / 10}%` : "0%";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Usage"
        description="Organization-wide gateway consumption, spend, latency, and error pressure."
        actions={
          <Select value={window} onValueChange={(value) => setWindow(value as UsageWindow)}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="24h">Last 24h</SelectItem>
              <SelectItem value="7d">Last 7d</SelectItem>
              <SelectItem value="30d">Last 30d</SelectItem>
              <SelectItem value="lifetime">Lifetime</SelectItem>
            </SelectContent>
          </Select>
        }
      />

      {usageQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading usage...</p>
      ) : !summary || requests === 0 ? (
        <EmptyState
          icon={ChartNoAxesCombined}
          title="No usage recorded"
          description="Proxy traffic will appear here once virtual keys start serving requests."
        />
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              label="Requests"
              value={requests.toLocaleString()}
              icon={ChartNoAxesCombined}
            />
            <MetricCard
              label="Tokens"
              value={(totals?.total_tokens ?? 0).toLocaleString()}
              detail={`${(totals?.prompt_tokens ?? 0).toLocaleString()} in / ${(totals?.completion_tokens ?? 0).toLocaleString()} out`}
              icon={Timer}
            />
            <MetricCard
              label="Spend"
              value={formatCents(totals?.cost_cents ?? 0)}
              icon={WalletCards}
            />
            <MetricCard
              label="Error rate"
              value={errorRate}
              detail={`${failed.toLocaleString()} failed`}
              icon={AlertTriangle}
            />
            <MetricCard
              label="Avg latency"
              value={totals?.average_latency_ms == null ? "-" : `${totals.average_latency_ms}ms`}
              icon={Clock}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <BreakdownCard title="Providers" rows={summary.by_provider} />
            <BreakdownCard title="Models" rows={summary.by_model} />
            <BreakdownCard title="Pools" rows={summary.by_pool} />
            <BreakdownCard title="Teams" rows={summary.by_team} />
            <BreakdownCard title="Projects" rows={summary.by_project} />
            <BreakdownCard title="Allocations" rows={summary.by_allocation} />
            <BreakdownCard title="Virtual keys" rows={summary.by_virtual_key} />
            <RecentDenialsCard events={summary.recent_denials} />
          </section>
        </>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail?: string;
  icon: typeof ChartNoAxesCombined;
}) {
  return (
    <Card size="sm">
      <CardContent>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm text-muted-foreground">{label}</div>
            <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
            {detail ? <div className="mt-1 text-xs text-muted-foreground">{detail}</div> : null}
          </div>
          <div className="rounded-md border bg-background p-2 text-muted-foreground">
            <Icon className="size-4" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function BreakdownCard({ title, rows }: { title: string; rows: UsageBreakdownRow[] }) {
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No usage</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Spend</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.slice(0, 8).map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="max-w-64 truncate">{row.label}</TableCell>
                  <TableCell className="text-right">
                    {(row.requests ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {(row.total_tokens ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">{formatCents(row.cost_cents ?? 0)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function RecentDenialsCard({ events }: { events: ActivityEventResponse[] }) {
  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Recent denials</CardTitle>
          <Badge variant="outline">{events.length}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent proxy denials or errors.</p>
        ) : (
          <div className="space-y-2">
            {events.slice(0, 8).map((event) => (
              <div key={event.id} className="rounded-md border bg-background p-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium">{event.message}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{event.action}</div>
                  </div>
                  <Badge variant={event.severity === "error" ? "destructive" : "secondary"}>
                    {event.severity}
                  </Badge>
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {new Date(event.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatCents(value: number) {
  return `$${(value / 100).toLocaleString()}`;
}
