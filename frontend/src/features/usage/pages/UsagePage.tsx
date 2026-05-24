import {
  AlertTriangle,
  ChartNoAxesCombined,
  Clock,
  Download,
  Timer,
  WalletCards,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { apiMutator } from "@/shared/api/orval-mutator";
import type { ActivityEventResponse, UsageBreakdownRow } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { useQuery } from "@tanstack/react-query";

type UsageWindow = "24h" | "7d" | "30d" | "lifetime";
type UsageRecordResponse = {
  id: string;
  created_at: string;
  provider_id: string;
  project_id: string;
  allocation_id: string;
  virtual_key_id: string;
  requested_model: string;
  provider_model: string;
  http_status: number;
  latency_ms: number;
  total_tokens: number | null;
  cost_cents: number | null;
  error_code: string | null;
};

export function UsagePage() {
  const [window, setWindow] = useState<UsageWindow>("30d");
  const [recordFilter, setRecordFilter] = useState("");
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet({ window });
  const recordsQuery = useQuery({
    queryKey: ["usage-records", window],
    queryFn: () =>
      apiMutator<UsageRecordResponse[]>(`/api/v1/usage/records?window=${window}&limit=100`),
  });
  const summary = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const records = Array.isArray(recordsQuery.data) ? recordsQuery.data : [];
  const filteredRecords = records.filter((record) => {
    const term = recordFilter.trim().toLowerCase();
    if (!term) return true;
    return `${record.requested_model} ${record.provider_model} ${record.http_status} ${record.error_code ?? ""} ${record.provider_id} ${record.project_id} ${record.allocation_id} ${record.virtual_key_id}`
      .toLowerCase()
      .includes(term);
  });
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
          <UsageRecordsCard
            records={filteredRecords}
            isLoading={recordsQuery.isPending}
            filter={recordFilter}
            onFilterChange={setRecordFilter}
          />
        </>
      )}
    </div>
  );
}

function UsageRecordsCard({
  records,
  isLoading,
  filter,
  onFilterChange,
}: {
  records: UsageRecordResponse[];
  isLoading: boolean;
  filter: string;
  onFilterChange: (value: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Usage records</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="h-9 w-72"
              value={filter}
              onChange={(event) => onFilterChange(event.target.value)}
              placeholder="Filter model, status, entity..."
            />
            <Button variant="outline" size="sm" onClick={() => downloadCsv(records)}>
              <Download data-icon="inline-start" />
              Export CSV
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading usage records...</p>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No matching usage records.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Spend</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.slice(0, 20).map((record) => (
                <TableRow key={record.id}>
                  <TableCell className="text-muted-foreground">
                    {new Date(record.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{record.requested_model}</div>
                    <div className="text-xs text-muted-foreground">{record.provider_model}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={record.http_status >= 400 ? "destructive" : "secondary"}>
                      {record.http_status}
                    </Badge>
                    {record.error_code ? (
                      <div className="mt-1 text-xs text-muted-foreground">{record.error_code}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right">
                    {(record.total_tokens ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatCents(record.cost_cents ?? 0)}
                  </TableCell>
                  <TableCell className="text-right">{record.latency_ms}ms</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function downloadCsv(records: UsageRecordResponse[]) {
  const header = [
    "created_at",
    "requested_model",
    "provider_model",
    "http_status",
    "total_tokens",
    "cost_cents",
    "latency_ms",
    "error_code",
  ];
  const rows = records.map((record) =>
    [
      record.created_at,
      record.requested_model,
      record.provider_model,
      record.http_status,
      record.total_tokens ?? 0,
      record.cost_cents ?? 0,
      record.latency_ms,
      record.error_code ?? "",
    ]
      .map((value) => `"${String(value).replaceAll('"', '""')}"`)
      .join(","),
  );
  const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-usage-records.csv";
  anchor.click();
  URL.revokeObjectURL(url);
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
