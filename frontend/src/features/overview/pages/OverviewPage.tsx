import { FolderKanban, Plug } from "lucide-react";
import { useQueryState } from "nuqs";
import { Link } from "react-router-dom";

import { useGetAnalyticsSummaryApiV1AnalyticsSummaryGet } from "@/shared/api/generated/analytics/analytics";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";
import { PageHeader } from "@/shared/components/PageHeader";

export function OverviewPage() {
  const [daysParam, setDaysParam] = useQueryState("days", { defaultValue: "7" });
  const days = clampDays(Number(daysParam) || 7);
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const summaryQuery = useGetAnalyticsSummaryApiV1AnalyticsSummaryGet({
    days,
    recent_limit: 10,
  });

  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const summary = summaryQuery.data?.status === 200 ? summaryQuery.data.data : null;

  const isLoading = projectsQuery.isPending || providersQuery.isPending || summaryQuery.isPending;

  if (!isLoading && projects.length === 0 && providers.length === 0) {
    return (
      <>
        <PageHeader title="Overview" description="Get started with your gateway." />
        <EmptyState
          icon={Plug}
          title="No providers or projects yet"
          description="Add a provider, then create a project to start routing traffic through Bab."
          action={
            <div className="flex gap-2">
              <Button asChild>
                <Link to="/providers">Add provider</Link>
              </Button>
              <Button variant="outline" asChild>
                <Link to="/projects">Create project</Link>
              </Button>
            </div>
          }
        />
      </>
    );
  }

  const failures = (summary?.recent_requests ?? []).filter((req) => req.http_status >= 400);

  return (
    <>
      <PageHeader
        title="Overview"
        description={`Last ${days} days across your gateway.`}
        actions={
          <Select value={String(days)} onValueChange={(value) => setDaysParam(value)}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Last day</SelectItem>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
            </SelectContent>
          </Select>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Requests"
          value={summary?.totals.request_count ?? 0}
          loading={summaryQuery.isPending}
        />
        <Metric
          label="Errors"
          value={summary?.totals.error_count ?? 0}
          loading={summaryQuery.isPending}
        />
        <Metric
          label="Total tokens"
          value={summary?.totals.total_tokens ?? 0}
          loading={summaryQuery.isPending}
        />
        <Metric
          label="Avg latency"
          value={`${summary?.totals.average_latency_ms ?? 0} ms`}
          loading={summaryQuery.isPending}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Top virtual keys</CardTitle>
            <CardDescription>Highest volume keys in the selected window.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead className="text-right">Requests</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(summary?.top_keys ?? []).map((key) => (
                  <TableRow key={key.virtual_key_id}>
                    <TableCell className="font-medium">{key.key_name}</TableCell>
                    <TableCell className="text-right tabular-nums">{key.request_count}</TableCell>
                    <TableCell className="text-right tabular-nums">{key.total_tokens}</TableCell>
                  </TableRow>
                ))}
                {summary && summary.top_keys.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      No usage yet.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent failures</CardTitle>
            <CardDescription>Requests with non-2xx status.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {failures.map((req) => (
                  <TableRow key={req.id}>
                    <TableCell className="text-muted-foreground">
                      {new Date(req.created_at).toLocaleTimeString()}
                    </TableCell>
                    <TableCell>
                      <HttpStatusBadge status={req.http_status} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{req.requested_model}</TableCell>
                    <TableCell className="text-muted-foreground">{req.error_code ?? "—"}</TableCell>
                  </TableRow>
                ))}
                {failures.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      No recent failures.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Daily traffic</CardTitle>
          <CardDescription>Requests and tokens per day.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Day</TableHead>
                <TableHead className="text-right">Requests</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(summary?.time_series ?? []).map((point) => (
                <TableRow key={point.bucket}>
                  <TableCell>{new Date(point.bucket).toLocaleDateString()}</TableCell>
                  <TableCell className="text-right tabular-nums">{point.request_count}</TableCell>
                  <TableCell className="text-right tabular-nums">{point.total_tokens}</TableCell>
                </TableRow>
              ))}
              {summary && summary.time_series.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground">
                    No traffic recorded yet.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Create a project to attach providers and issue virtual keys."
          action={
            <Button asChild>
              <Link to="/projects">Create project</Link>
            </Button>
          }
        />
      ) : null}
    </>
  );
}

function Metric({
  label,
  value,
  loading,
}: {
  label: string;
  value: string | number;
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">
          {loading ? <Skeleton className="h-8 w-24" /> : value}
        </CardTitle>
      </CardHeader>
    </Card>
  );
}

function clampDays(value: number) {
  if (value < 1) return 1;
  if (value > 90) return 90;
  return value;
}
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
