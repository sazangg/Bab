import {
  AlertTriangle,
  CalendarDays,
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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
import {
  useGetOrganizationUsageSummaryApiV1UsageSummaryGet,
  useGetOrganizationUsageTimeseriesApiV1UsageTimeseriesGet,
  useGetSpendInsightsApiV1UsageSpendInsightsGet,
  useListUsageRecordsApiV1UsageRecordsGet,
} from "@/shared/api/generated/usage/usage";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { httpClient } from "@/shared/api/http-client";
import { canViewUsage, hasPermission } from "@/features/auth/lib/permissions";
import type {
  ActivityEventResponse,
  AuthenticatedUser,
  LimitPolicyBudgetBurnRow,
  ProjectResponse,
  TeamResponse,
  UsageRecordResponse,
  UsageBreakdownRow,
  UsageTimeSeriesPoint,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

type UsageWindow = "24h" | "7d" | "30d" | "90d" | "lifetime";
type UsageGrain = "hour" | "day" | "week";
type UsageChartMetric = "requests" | "spend" | "tokens";
type UsageScopeValue = "authorized" | `team:${string}` | `project:${string}`;

export function UsagePage() {
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const [window, setWindow] = useState<UsageWindow>("30d");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [customRangeEnabled, setCustomRangeEnabled] = useState(false);
  const [providerId, setProviderId] = useState("all");
  const [teamId, setTeamId] = useState("all");
  const [projectId, setProjectId] = useState("all");
  const [model, setModel] = useState("all");
  const [virtualKeyId, setVirtualKeyId] = useState("all");
  const [scopeValue, setScopeValue] = useState<UsageScopeValue>("authorized");
  const [recordFilter, setRecordFilter] = useState("");
  const [chartMetric, setChartMetric] = useState<UsageChartMetric>("spend");
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canViewOrgUsage = hasPermission(currentUser, "usage.view");
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const usageScopes = buildUsageScopes({ canViewOrgUsage, teams, projects, currentUser });
  const selectedUsageScope = usageScopes.some((scope) => scope.value === scopeValue)
    ? scopeValue
    : "authorized";
  const grain = getUsageGrain(window, customRangeEnabled, startDate, endDate);
  const usageParams = buildUsageParams({
    window,
    startDate: customRangeEnabled ? startDate : "",
    endDate: customRangeEnabled ? endDate : "",
    providerId,
    teamId,
    projectId,
    model,
    virtualKeyId,
    scopeValue: canViewOrgUsage ? "authorized" : selectedUsageScope,
  });
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet(usageParams);
  const timeseriesQuery = useGetOrganizationUsageTimeseriesApiV1UsageTimeseriesGet({
    ...usageParams,
    grain,
  });
  const spendInsightsQuery = useGetSpendInsightsApiV1UsageSpendInsightsGet({
    ...usageParams,
  });
  const recordsQuery = useListUsageRecordsApiV1UsageRecordsGet({
    ...usageParams,
    limit: 100,
  });
  const summary = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const spendInsights =
    spendInsightsQuery.data?.status === 200 ? spendInsightsQuery.data.data : null;
  const timeseries = timeseriesQuery.data?.status === 200 ? timeseriesQuery.data.data : [];
  const records = recordsQuery.data?.status === 200 ? recordsQuery.data.data : [];
  const filteredRecords = records.filter((record) => {
    const term = recordFilter.trim().toLowerCase();
    if (!term) return true;
    return `${record.requested_model} ${record.provider_model} ${record.provider_credential_name ?? ""} ${record.provider_credential_prefix ?? ""} ${record.request_id ?? ""} ${record.http_status} ${record.error_code ?? ""} ${record.provider_id} ${record.project_id} ${record.access_policy_id ?? ""} ${record.virtual_key_id}`
      .toLowerCase()
      .includes(term);
  });
  const totals = summary?.totals;
  const requests = totals?.requests ?? 0;
  const failed = totals?.failed_requests ?? 0;
  const errorRate = requests > 0 ? `${Math.round((failed / requests) * 1000) / 10}%` : "0%";
  const providerOptions = summary?.by_provider ?? [];
  const teamOptions = summary?.by_team ?? [];
  const projectOptions = summary?.by_project ?? [];
  const modelOptions = summary?.by_model ?? [];
  const virtualKeyOptions = summary?.by_virtual_key ?? [];
  const pageDescription = canViewOrgUsage
    ? "Organization-wide gateway consumption, spend, latency, and errors."
    : "Usage for your authorized teams and directly administered projects.";

  if (currentUserQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Checking usage access...</p>;
  }

  if (!canViewUsage(currentUser)) {
    return (
      <EmptyState
        icon={ChartNoAxesCombined}
        title="No usage access"
        description="Your account does not have an organization, team, or project usage scope."
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Usage"
        description={pageDescription}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={window}
              onValueChange={(value) => {
                setWindow(value as UsageWindow);
                setCustomRangeEnabled(false);
              }}
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="24h">Last 24h</SelectItem>
                <SelectItem value="7d">Last 7d</SelectItem>
                <SelectItem value="30d">Last 30d</SelectItem>
                <SelectItem value="90d">Last 90d</SelectItem>
                <SelectItem value="lifetime">Lifetime</SelectItem>
              </SelectContent>
            </Select>
            <DateRangePopover
              startDate={startDate}
              endDate={endDate}
              enabled={customRangeEnabled}
              onStartDateChange={setStartDate}
              onEndDateChange={setEndDate}
              onApply={() => setCustomRangeEnabled(Boolean(startDate || endDate))}
              onClear={() => {
                setStartDate("");
                setEndDate("");
                setCustomRangeEnabled(false);
              }}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setProviderId("all");
                setTeamId("all");
                setProjectId("all");
                setModel("all");
                setVirtualKeyId("all");
                setScopeValue("authorized");
                setRecordFilter("");
              }}
            >
              Clear filters
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {!canViewOrgUsage ? (
            <ScopeSelect
              value={selectedUsageScope}
              scopes={usageScopes}
              onChange={(value) => {
                setScopeValue(value);
                setProviderId("all");
                setModel("all");
                setVirtualKeyId("all");
              }}
            />
          ) : null}
          <UsageSelect
            label="Provider"
            value={providerId}
            placeholder="All providers"
            options={providerOptions}
            onChange={setProviderId}
          />
          {canViewOrgUsage ? (
            <>
              <UsageSelect
                label="Team"
                value={teamId}
                placeholder="All teams"
                options={teamOptions}
                onChange={setTeamId}
              />
              <UsageSelect
                label="Project"
                value={projectId}
                placeholder="All projects"
                options={projectOptions}
                onChange={setProjectId}
              />
            </>
          ) : null}
          <UsageSelect
            label="Model"
            value={model}
            placeholder="All models"
            options={modelOptions}
            onChange={setModel}
          />
          <UsageSelect
            label="Virtual key"
            value={virtualKeyId}
            placeholder="All keys"
            options={virtualKeyOptions}
            onChange={setVirtualKeyId}
          />
        </CardContent>
      </Card>

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
              label="Confirmed spend"
              value={formatCents(totals?.confirmed_spend_cents ?? 0)}
              detail={`${formatCents(totals?.estimated_spend_cents ?? 0)} estimated`}
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
              detail={
                (totals?.unknown_usage_count ?? 0) > 0
                  ? `${totals?.unknown_usage_count ?? 0} unpriced`
                  : undefined
              }
              icon={Clock}
            />
          </section>

          <UsageTrendCard
            points={timeseries}
            grain={grain}
            metric={chartMetric}
            onMetricChange={setChartMetric}
            isLoading={timeseriesQuery.isPending}
          />

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,480px)]">
            <SpendDriversCard rows={spendInsights?.top_spend_drivers ?? summary.by_model} />
            <BudgetBurnCard rows={spendInsights?.limit_policy_budget_burn ?? []} />
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <BreakdownCard title="Providers" rows={summary.by_provider} onSelect={setProviderId} />
            <BreakdownCard title="Models" rows={summary.by_model} onSelect={setModel} />
            <BreakdownCard title="Pools" rows={summary.by_pool} />
            {canViewOrgUsage ? (
              <>
                <BreakdownCard title="Teams" rows={summary.by_team} />
                <BreakdownCard title="Projects" rows={summary.by_project} />
              </>
            ) : (
              <BreakdownCard title="Authorized scopes" rows={scopeBreakdown(summary)} />
            )}
            <BreakdownCard title="Access policies" rows={summary.by_access_policy} />
            <BreakdownCard
              title="Virtual keys"
              rows={summary.by_virtual_key}
              onSelect={setVirtualKeyId}
            />
            <RecentDenialsCard events={summary.recent_denials} />
          </section>
        <UsageRecordsCard
          records={filteredRecords}
          isLoading={recordsQuery.isPending}
          filter={recordFilter}
          onFilterChange={setRecordFilter}
          exportParams={usageParams}
        />
        </>
      )}
    </div>
  );
}

function DateRangePopover({
  startDate,
  endDate,
  enabled,
  onStartDateChange,
  onEndDateChange,
  onApply,
  onClear,
}: {
  startDate: string;
  endDate: string;
  enabled: boolean;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onApply: () => void;
  onClear: () => void;
}) {
  const label = enabled ? `${startDate || "Start"} - ${endDate || "Today"}` : "Custom range";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline">
          <CalendarDays data-icon="inline-start" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <div className="flex flex-col gap-4">
          <div>
            <div className="font-medium">Usage date range</div>
            <div className="text-sm text-muted-foreground">
              Filter summaries, charts, and raw records by explicit dates.
            </div>
          </div>
          <div className="grid gap-3">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Start</span>
              <Input
                type="date"
                value={startDate}
                onChange={(event) => onStartDateChange(event.target.value)}
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">End</span>
              <Input
                type="date"
                value={endDate}
                onChange={(event) => onEndDateChange(event.target.value)}
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClear}>
              Clear
            </Button>
            <Button onClick={onApply}>Apply</Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function UsageSelect({
  label,
  value,
  placeholder,
  options,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  options: UsageBreakdownRow[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{placeholder}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

function ScopeSelect({
  value,
  scopes,
  onChange,
}: {
  value: UsageScopeValue;
  scopes: UsageScopeOption[];
  onChange: (value: UsageScopeValue) => void;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">Scope</span>
      <Select value={value} onValueChange={(nextValue) => onChange(nextValue as UsageScopeValue)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {scopes.map((scope) => (
            <SelectItem key={scope.value} value={scope.value}>
              {scope.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

function UsageTrendCard({
  points,
  grain,
  metric,
  onMetricChange,
  isLoading,
}: {
  points: UsageTimeSeriesPoint[];
  grain: UsageGrain;
  metric: UsageChartMetric;
  onMetricChange: (value: UsageChartMetric) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Usage trend</CardTitle>
          <div className="flex items-center gap-2">
            <Select
              value={metric}
              onValueChange={(value) => onMetricChange(value as UsageChartMetric)}
            >
              <SelectTrigger className="h-8 w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="spend">Spend</SelectItem>
                <SelectItem value="requests">Requests</SelectItem>
                <SelectItem value="tokens">Tokens</SelectItem>
              </SelectContent>
            </Select>
            <Badge variant="outline">{grain}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading trend...</p>
        ) : points.length === 0 ? (
          <p className="text-sm text-muted-foreground">No usage in this range.</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
            <MiniBarChart points={points} metric={metric} />
            <div className="grid gap-2 text-sm">
              <TrendStat
                label="Peak requests"
                value={Math.max(...points.map((point) => point.requests ?? 0)).toLocaleString()}
              />
              <TrendStat
                label="Peak tokens"
                value={Math.max(...points.map((point) => point.total_tokens ?? 0)).toLocaleString()}
              />
              <TrendStat
                label="Confirmed spend"
                value={formatCents(
                  points.reduce((sum, point) => sum + (point.confirmed_spend_cents ?? 0), 0),
                )}
              />
              <TrendStat
                label="Estimated spend"
                value={formatCents(
                  points.reduce((sum, point) => sum + (point.estimated_spend_cents ?? 0), 0),
                )}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MiniBarChart({
  points,
  metric,
}: {
  points: UsageTimeSeriesPoint[];
  metric: UsageChartMetric;
}) {
  const values = points.map((point) => metricValue(point, metric));
  const maxValue = Math.max(...values, 1);
  return (
    <div className="flex h-56 items-end gap-1 rounded-md border bg-muted/20 p-3">
      {points.map((point) => {
        const value = metricValue(point, metric);
        const height = Math.max(4, Math.round((value / maxValue) * 100));
        return (
          <div key={point.bucket} className="group flex min-w-3 flex-1 items-end">
            <div
              className="w-full rounded-t bg-primary/70 transition-colors group-hover:bg-primary"
              style={{ height: `${height}%` }}
              title={`${formatBucket(point.bucket)}: ${formatMetricValue(value, metric)}`}
            />
          </div>
        );
      })}
    </div>
  );
}

function TrendStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function SpendCell({
  confirmed,
  estimated,
  unknown,
}: {
  confirmed?: number | null;
  estimated?: number | null;
  unknown?: boolean;
}) {
  if (unknown) {
    return <span className="text-muted-foreground">Unpriced</span>;
  }
  if ((confirmed ?? 0) > 0) {
    return (
      <div>
        <div>{formatCents(confirmed ?? 0)}</div>
        <div className="text-xs text-muted-foreground">confirmed</div>
      </div>
    );
  }
  return (
    <div>
      <div>{formatCents(estimated ?? 0)}</div>
      <div className="text-xs text-muted-foreground">estimated</div>
    </div>
  );
}

function UsageRecordsCard({
  records,
  isLoading,
  filter,
  onFilterChange,
  exportParams,
}: {
  records: UsageRecordResponse[];
  isLoading: boolean;
  filter: string;
  onFilterChange: (value: string) => void;
  exportParams: ReturnType<typeof buildUsageParams>;
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
            <Button variant="outline" size="sm" onClick={() => downloadUsageExport(exportParams)}>
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
                <TableHead>Credential</TableHead>
                <TableHead>Request</TableHead>
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
                    <div className="font-medium">
                      {record.provider_credential_name ?? "Unknown"}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {record.provider_credential_prefix ?? shortId(record.provider_credential_id)}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {shortId(record.request_id)}
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
                    <SpendCell
                      confirmed={record.confirmed_spend_cents}
                      estimated={record.estimated_spend_cents}
                      unknown={record.spend_type === "unknown"}
                    />
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

function SpendDriversCard({ rows }: { rows: UsageBreakdownRow[] }) {
  const maxSpend = Math.max(...rows.map((row) => row.cost_cents ?? 0), 0);
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>Top spend drivers</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No priced usage in this range.</p>
        ) : (
          <div className="space-y-3">
            {rows.slice(0, 8).map((row) => {
              const spend = row.cost_cents ?? 0;
              const width = maxSpend ? Math.max(3, (spend / maxSpend) * 100) : 0;
              return (
                <div key={row.id} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate font-medium">{row.label}</span>
                    <span className="shrink-0 text-muted-foreground">
                      {formatSpendParts(row)}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{(row.requests ?? 0).toLocaleString()} requests</span>
                    <span>{(row.total_tokens ?? 0).toLocaleString()} tokens</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BudgetBurnCard({ rows }: { rows: LimitPolicyBudgetBurnRow[] }) {
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>Budget burn</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No active limit policies with budgets in this range.
          </p>
        ) : (
          <div className="space-y-3">
            {rows.slice(0, 8).map((row) => {
              const burn = Math.min(row.burn_rate_pct, 100);
              return (
                <div key={row.limit_policy_id} className="rounded-md border bg-background p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{row.limit_policy_name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {row.interval}
                      </div>
                    </div>
                    <Badge variant={row.burn_rate_pct >= 90 ? "destructive" : "outline"}>
                      {row.burn_rate_pct}%
                    </Badge>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${burn}%` }} />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                    <span>{formatCents(row.spent_cents)} spent</span>
                    <span>{formatCents(row.remaining_cents)} left</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

async function downloadUsageExport(params: ReturnType<typeof buildUsageParams>) {
  const response = await httpClient.get<Blob>("/api/v1/usage/records/export", {
    params,
    responseType: "blob",
  });
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-usage-records.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function buildUsageParams({
  window,
  startDate,
  endDate,
  providerId,
  teamId,
  projectId,
  model,
  virtualKeyId,
  scopeValue,
}: {
  window: UsageWindow;
  startDate: string;
  endDate: string;
  providerId: string;
  teamId: string;
  projectId: string;
  model: string;
  virtualKeyId: string;
  scopeValue: UsageScopeValue;
}) {
  const params: {
    window: UsageWindow;
    start_at?: string;
    end_at?: string;
    provider_id?: string;
    team_id?: string;
    project_id?: string;
    model?: string;
    virtual_key_id?: string;
  } = { window };
  if (startDate) {
    params.start_at = new Date(`${startDate}T00:00:00`).toISOString();
  }
  if (endDate) {
    params.end_at = new Date(`${endDate}T23:59:59`).toISOString();
  }
  if (providerId !== "all") {
    params.provider_id = providerId;
  }
  const scopedTeamId = scopeValue.startsWith("team:") ? scopeValue.slice("team:".length) : null;
  const scopedProjectId = scopeValue.startsWith("project:")
    ? scopeValue.slice("project:".length)
    : null;
  if (scopedTeamId) {
    params.team_id = scopedTeamId;
  } else if (teamId !== "all") {
    params.team_id = teamId;
  }
  if (scopedProjectId) {
    params.project_id = scopedProjectId;
  } else if (projectId !== "all") {
    params.project_id = projectId;
  }
  if (model !== "all") {
    params.model = model;
  }
  if (virtualKeyId !== "all") {
    params.virtual_key_id = virtualKeyId;
  }
  return params;
}

type UsageScopeOption = {
  value: UsageScopeValue;
  label: string;
};

function buildUsageScopes({
  canViewOrgUsage,
  teams,
  projects,
  currentUser,
}: {
  canViewOrgUsage: boolean;
  teams: TeamResponse[];
  projects: ProjectResponse[];
  currentUser: AuthenticatedUser | null;
}): UsageScopeOption[] {
  if (canViewOrgUsage) {
    return [{ value: "authorized", label: "Organization" }];
  }
  const teamById = Object.fromEntries(teams.map((team) => [team.id, team]));
  const projectById = Object.fromEntries(projects.map((project) => [project.id, project]));
  const options: UsageScopeOption[] = [{ value: "authorized", label: "All authorized usage" }];
  for (const membership of currentUser?.team_memberships ?? []) {
    options.push({
      value: `team:${membership.team_id}`,
      label: teamById[membership.team_id]?.name ?? `Team ${shortId(membership.team_id)}`,
    });
  }
  for (const membership of currentUser?.project_memberships ?? []) {
    const project = projectById[membership.project_id];
    const team = project ? teamById[project.team_id] : null;
    options.push({
      value: `project:${membership.project_id}`,
      label: `${project?.name ?? `Project ${shortId(membership.project_id)}`}${
        team ? ` (${team.name})` : ""
      }`,
    });
  }
  return dedupeScopes(options);
}

function dedupeScopes(options: UsageScopeOption[]) {
  const seen = new Set<UsageScopeValue>();
  return options.filter((option) => {
    if (seen.has(option.value)) return false;
    seen.add(option.value);
    return true;
  });
}

function scopeBreakdown(summary: {
  by_team: UsageBreakdownRow[];
  by_project: UsageBreakdownRow[];
}) {
  return [...summary.by_team, ...summary.by_project];
}

function getUsageGrain(
  window: UsageWindow,
  customRangeEnabled: boolean,
  startDate: string,
  endDate: string,
): UsageGrain {
  if (window === "24h") return "hour";
  if (window === "90d" || window === "lifetime") return "week";
  if (customRangeEnabled && startDate && endDate) {
    const start = new Date(startDate);
    const end = new Date(endDate);
    const days = Math.max(1, (end.getTime() - start.getTime()) / 86_400_000);
    if (days <= 2) return "hour";
    if (days > 60) return "week";
  }
  return "day";
}

function formatBucket(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
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

function BreakdownCard({
  title,
  rows,
  onSelect,
}: {
  title: string;
  rows: UsageBreakdownRow[];
  onSelect?: (id: string) => void;
}) {
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
                <TableRow
                  key={row.id}
                  className={onSelect ? "cursor-pointer" : undefined}
                  onClick={() => onSelect?.(row.id)}
                >
                  <TableCell className="max-w-64 truncate">{row.label}</TableCell>
                  <TableCell className="text-right">
                    {(row.requests ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {(row.total_tokens ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">{formatSpendParts(row)}</TableCell>
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

function formatSpendParts(row: {
  confirmed_spend_cents?: number;
  estimated_spend_cents?: number;
  unknown_usage_count?: number;
  cost_cents?: number;
}) {
  const confirmed = row.confirmed_spend_cents ?? 0;
  const estimated = row.estimated_spend_cents ?? 0;
  const unknown = row.unknown_usage_count ?? 0;
  const parts = [];
  if (confirmed > 0) parts.push(`${formatCents(confirmed)} confirmed`);
  if (estimated > 0) parts.push(`${formatCents(estimated)} estimated`);
  if (unknown > 0) parts.push(`${unknown.toLocaleString()} unpriced`);
  return parts.length > 0 ? parts.join(" / ") : formatCents(row.cost_cents ?? 0);
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}

function metricValue(point: UsageTimeSeriesPoint, metric: UsageChartMetric) {
  if (metric === "spend") {
    return (point.confirmed_spend_cents ?? 0) + (point.estimated_spend_cents ?? 0);
  }
  if (metric === "tokens") return point.total_tokens ?? 0;
  return point.requests ?? 0;
}

function formatMetricValue(value: number, metric: UsageChartMetric) {
  if (metric === "spend") return formatCents(value);
  if (metric === "tokens") return `${value.toLocaleString()} tokens`;
  return `${value.toLocaleString()} requests`;
}
