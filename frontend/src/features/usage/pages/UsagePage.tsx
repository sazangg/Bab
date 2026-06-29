import {
  AlertTriangle,
  CalendarDays,
  ChartNoAxesCombined,
  Clock,
  Download,
  Eye,
  Timer,
  WalletCards,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { DataTable } from "@/components/ui/data-table";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useGetOrganizationUsageSummaryApiV1UsageSummaryGet,
  useGetOrganizationUsageTimeseriesApiV1UsageTimeseriesGet,
  useGetSpendInsightsApiV1UsageSpendInsightsGet,
} from "@/shared/api/generated/usage/usage";
import { useListGatewayRequestsApiV1GatewayHistoryRequestsGet } from "@/shared/api/generated/gateway-history/gateway-history";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { httpClient } from "@/shared/api/http-client";
import { getProblemDetail } from "@/shared/api/problem-detail";
import { canViewUsage, hasPermission } from "@/features/auth/lib/permissions";
import type {
  ActivityEventResponse,
  AuthenticatedUser,
  GatewayRequestTraceListItem,
  LimitPolicyBudgetBurnRow,
  ProjectResponse,
  TeamResponse,
  UsageRecordPageResponse,
  UsageRecordResponse,
  UsageBreakdownRow,
  UsageTimeSeriesPoint,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { formatCents } from "@/shared/lib/format-currency";
import { PageHeader } from "@/shared/components/PageHeader";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";
import { RequestTraceSheet } from "@/features/usage/components/RequestTraceSheet";

type UsageWindow = "24h" | "7d" | "30d" | "90d" | "lifetime";
type UsageGrain = "hour" | "day" | "week";
type UsageChartMetric = "requests" | "spend" | "tokens";
type UsageScopeValue = "authorized" | `team:${string}` | `project:${string}`;
type UsageFilterOptions = {
  by_provider: UsageBreakdownRow[];
  by_model: UsageBreakdownRow[];
  by_team: UsageBreakdownRow[];
  by_project: UsageBreakdownRow[];
  by_virtual_key: UsageBreakdownRow[];
};

const RECORDS_PAGE_SIZE = 25;
const REQUESTS_PAGE_SIZE = 25;

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
  const [activeTraceTab, setActiveTraceTab] = useState("requests");
  const [requestSearch, setRequestSearch] = useState("");
  const [requestPage, setRequestPage] = useState(0);
  const [recordSearch, setRecordSearch] = useState("");
  const [recordPage, setRecordPage] = useState(0);
  const [chartMetric, setChartMetric] = useState<UsageChartMetric>("spend");
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null);
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canViewOrgUsage = hasPermission(currentUser, "usage.view");
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const usageScopes = buildUsageScopes({ canViewOrgUsage, teams, projects, currentUser });
  const selectedUsageScope = usageScopes.some((scope) => scope.value === scopeValue)
    ? scopeValue
    : "authorized";
  const grain = getUsageGrain(window, customRangeEnabled, startDate, endDate);
  const usageParams = useMemo(
    () =>
      buildUsageParams({
        window,
        startDate: customRangeEnabled ? startDate : "",
        endDate: customRangeEnabled ? endDate : "",
        providerId,
        teamId,
        projectId,
        model,
        virtualKeyId,
        scopeValue: canViewOrgUsage ? "authorized" : selectedUsageScope,
      }),
    [
      canViewOrgUsage,
      customRangeEnabled,
      endDate,
      model,
      projectId,
      providerId,
      selectedUsageScope,
      startDate,
      teamId,
      virtualKeyId,
      window,
    ],
  );
  const filterOptionParams = useMemo(
    () =>
      buildUsageParams({
        window,
        startDate: customRangeEnabled ? startDate : "",
        endDate: customRangeEnabled ? endDate : "",
        providerId: "all",
        teamId: "all",
        projectId: "all",
        model: "all",
        virtualKeyId: "all",
        scopeValue: canViewOrgUsage ? "authorized" : selectedUsageScope,
      }),
    [canViewOrgUsage, customRangeEnabled, endDate, selectedUsageScope, startDate, window],
  );
  const usageQuery = useGetOrganizationUsageSummaryApiV1UsageSummaryGet(usageParams);
  const timeseriesQuery = useGetOrganizationUsageTimeseriesApiV1UsageTimeseriesGet({
    ...usageParams,
    grain,
  });
  const spendInsightsQuery = useGetSpendInsightsApiV1UsageSpendInsightsGet({
    ...usageParams,
  });
  const resetTracePages = () => {
    setRequestPage(0);
    setRecordPage(0);
  };
  const trimmedRequestSearch = requestSearch.trim();
  const trimmedRecordSearch = recordSearch.trim();
  const requestParams = useMemo(() => {
    const { model: publicModelName, ...baseParams } = usageParams;
    return {
      ...baseParams,
      public_model_name: publicModelName,
      search: trimmedRequestSearch || undefined,
      limit: REQUESTS_PAGE_SIZE,
      offset: requestPage * REQUESTS_PAGE_SIZE,
    };
  }, [requestPage, trimmedRequestSearch, usageParams]);
  const requestsQuery = useListGatewayRequestsApiV1GatewayHistoryRequestsGet(requestParams);
  const recordsQuery = useQuery({
    queryKey: ["usage-records", usageParams, trimmedRecordSearch, recordPage],
    queryFn: async () => {
      const response = await httpClient.get<UsageRecordPageResponse>("/api/v1/usage/records", {
        params: {
          ...usageParams,
          search: trimmedRecordSearch || undefined,
          limit: RECORDS_PAGE_SIZE,
          offset: recordPage * RECORDS_PAGE_SIZE,
        },
      });
      return response.data;
    },
  });
  const filterOptionsQuery = useQuery({
    queryKey: ["usage-filter-options", filterOptionParams],
    queryFn: async () => {
      const response = await httpClient.get<UsageFilterOptions>("/api/v1/usage/filter-options", {
        params: filterOptionParams,
      });
      return response.data;
    },
  });
  const summary = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const spendInsights =
    spendInsightsQuery.data?.status === 200 ? spendInsightsQuery.data.data : null;
  const timeseries = timeseriesQuery.data?.status === 200 ? timeseriesQuery.data.data : [];
  const normalizedTimeseries = fillTimeSeriesGaps(
    timeseries,
    grain,
    window,
    customRangeEnabled,
    startDate,
    endDate,
  );
  const visibleRecords = recordsQuery.data?.items ?? [];
  const hasNextRecordsPage = recordsQuery.data?.has_more ?? false;
  const requestList =
    requestsQuery.data?.status === 200
      ? requestsQuery.data.data
      : { items: [], has_more: false, limit: REQUESTS_PAGE_SIZE, offset: requestPage * REQUESTS_PAGE_SIZE };
  const totals = summary?.totals;
  const requests = totals?.requests ?? 0;
  const failed = totals?.failed_requests ?? 0;
  const errorRate = requests > 0 ? `${Math.round((failed / requests) * 1000) / 10}%` : "0%";
  const filterOptions = filterOptionsQuery.data;
  const providerOptions = filterOptions?.by_provider ?? summary?.by_provider ?? [];
  const teamOptions = filterOptions?.by_team ?? summary?.by_team ?? [];
  const projectOptions = filterOptions?.by_project ?? summary?.by_project ?? [];
  const modelOptions = filterOptions?.by_model ?? summary?.by_model ?? [];
  const virtualKeyOptions = filterOptions?.by_virtual_key ?? summary?.by_virtual_key ?? [];
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
                resetTracePages();
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
              onApply={() => {
                setCustomRangeEnabled(Boolean(startDate || endDate));
                resetTracePages();
              }}
              onClear={() => {
                setStartDate("");
                setEndDate("");
                setCustomRangeEnabled(false);
                resetTracePages();
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
                setRequestSearch("");
                setRecordSearch("");
                resetTracePages();
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
                setTeamId("all");
                setProjectId("all");
                setModel("all");
                setVirtualKeyId("all");
                resetTracePages();
              }}
            />
          ) : null}
          <UsageSelect
            label="Provider"
            value={providerId}
            placeholder="All providers"
            options={providerOptions}
            onChange={(value) => {
              setProviderId(value);
              resetTracePages();
            }}
          />
          {canViewOrgUsage ? (
            <>
              <UsageSelect
                label="Team"
                value={teamId}
                placeholder="All teams"
                options={teamOptions}
                onChange={(value) => {
                  setTeamId(value);
                  setProjectId("all");
                  setVirtualKeyId("all");
                  resetTracePages();
                }}
              />
              <UsageSelect
                label="Project"
                value={projectId}
                placeholder="All projects"
                options={projectOptions}
                onChange={(value) => {
                  setProjectId(value);
                  setVirtualKeyId("all");
                  const project = projects.find((candidate) => candidate.id === value);
                  if (value !== "all" && project) {
                    setTeamId(project.team_id);
                  }
                  resetTracePages();
                }}
              />
            </>
          ) : null}
          <UsageSelect
            label="Model"
            value={model}
            placeholder="All models"
            options={modelOptions}
            onChange={(value) => {
              setModel(value);
              resetTracePages();
            }}
          />
          <UsageSelect
            label="Virtual key"
            value={virtualKeyId}
            placeholder="All keys"
            options={virtualKeyOptions}
            onChange={(value) => {
              setVirtualKeyId(value);
              resetTracePages();
            }}
          />
        </CardContent>
      </Card>

      {filterOptionsQuery.isError ? (
        <UsageErrorAlert
          title="Filter options failed"
          error={filterOptionsQuery.error}
          fallback="Unable to load usage filter options."
          onRetry={() => filterOptionsQuery.refetch()}
        />
      ) : null}

      {usageQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading usage...</p>
      ) : usageQuery.isError ? (
        <UsageErrorAlert
          title="Usage summary failed"
          error={usageQuery.error}
          fallback="Unable to load usage summary."
          onRetry={() => usageQuery.refetch()}
        />
      ) : !summary ? (
        <EmptyState
          icon={ChartNoAxesCombined}
          title="No usage recorded"
          description="Proxy traffic will appear here once virtual keys start serving requests."
        />
      ) : requests === 0 ? (
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
              label="Spend from reported usage"
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
            points={normalizedTimeseries}
            grain={grain}
            metric={chartMetric}
            onMetricChange={setChartMetric}
            isLoading={timeseriesQuery.isPending}
            error={timeseriesQuery.error}
            onRetry={() => timeseriesQuery.refetch()}
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
        </>
      )}

      {summary && requests === 0 ? (
        <section className="grid gap-4 xl:grid-cols-2">
          <RecentDenialsCard events={summary.recent_denials} />
        </section>
      ) : null}

      {summary ? (
        <GatewayTraceCard
          activeTab={activeTraceTab}
          onActiveTabChange={setActiveTraceTab}
          requests={requestList.items}
          requestsHasNext={requestList.has_more}
          requestsPage={requestPage}
          requestsPageSize={REQUESTS_PAGE_SIZE}
          requestsLoading={requestsQuery.isPending}
          requestsError={requestsQuery.error}
          requestFilter={requestSearch}
          onRequestFilterChange={(value) => {
            setRequestSearch(value);
            setRequestPage(0);
          }}
          onPreviousRequestPage={() => setRequestPage((page) => Math.max(0, page - 1))}
          onNextRequestPage={() => setRequestPage((page) => page + 1)}
          onRetryRequests={() => requestsQuery.refetch()}
          records={visibleRecords}
          recordsLoading={recordsQuery.isPending}
          recordsError={recordsQuery.error}
          recordFilter={recordSearch}
          onRecordFilterChange={(value) => {
            setRecordSearch(value);
            setRecordPage(0);
          }}
          exportParams={{
            ...usageParams,
            search: trimmedRecordSearch || undefined,
          }}
          recordsPage={recordPage}
          recordsPageSize={RECORDS_PAGE_SIZE}
          recordsHasNext={hasNextRecordsPage}
          onPreviousRecordPage={() => setRecordPage((page) => Math.max(0, page - 1))}
          onNextRecordPage={() => setRecordPage((page) => page + 1)}
          onRetryRecords={() => recordsQuery.refetch()}
          onOpenRequestTrace={(request) => setTraceRequestId(request.id)}
          onOpenRecordTrace={(record) => setTraceRequestId(record.gateway_request_id ?? null)}
        />
      ) : null}
      <RequestTraceSheet
        gatewayRequestId={traceRequestId}
        open={Boolean(traceRequestId)}
        onOpenChange={(open) => {
          if (!open) setTraceRequestId(null);
        }}
      />
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
  error,
  onRetry,
}: {
  points: UsageTimeSeriesPoint[];
  grain: UsageGrain;
  metric: UsageChartMetric;
  onMetricChange: (value: UsageChartMetric) => void;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
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
        ) : error ? (
          <UsageErrorAlert
            title="Trend failed"
            error={error}
            fallback="Unable to load the usage trend."
            onRetry={onRetry}
          />
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
                label="Spend from reported usage"
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

const METRIC_LABELS: Record<UsageChartMetric, string> = {
  spend: "Spend",
  requests: "Requests",
  tokens: "Tokens",
};

function MiniBarChart({
  points,
  metric,
}: {
  points: UsageTimeSeriesPoint[];
  metric: UsageChartMetric;
}) {
  const data = points.map((point) => ({
    bucket: formatBucket(point.bucket),
    value: metricValue(point, metric),
  }));
  const config: ChartConfig = {
    value: { label: METRIC_LABELS[metric], color: "var(--chart-1)" },
  };
  return (
    <ChartContainer config={config} className="h-56">
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id="usage-trend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-value)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-value)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="bucket" tickLine={false} axisLine={false} tickMargin={8} minTickGap={28} />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={48}
          tickFormatter={(value: number) => formatMetricValue(value, metric)}
        />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          content={
            <ChartTooltipContent
              valueFormatter={(value) => formatMetricValue(Number(value ?? 0), metric)}
            />
          }
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-value)"
          strokeWidth={2}
          fill="url(#usage-trend-fill)"
        />
      </AreaChart>
    </ChartContainer>
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
        <div className="text-xs text-muted-foreground">reported usage</div>
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

function GatewayTraceCard({
  activeTab,
  onActiveTabChange,
  requests,
  requestsHasNext,
  requestsPage,
  requestsPageSize,
  requestsLoading,
  requestsError,
  requestFilter,
  onRequestFilterChange,
  onPreviousRequestPage,
  onNextRequestPage,
  onRetryRequests,
  records,
  recordsLoading,
  recordsError,
  recordFilter,
  onRecordFilterChange,
  exportParams,
  recordsPage,
  recordsPageSize,
  recordsHasNext,
  onPreviousRecordPage,
  onNextRecordPage,
  onRetryRecords,
  onOpenRequestTrace,
  onOpenRecordTrace,
}: {
  activeTab: string;
  onActiveTabChange: (value: string) => void;
  requests: GatewayRequestTraceListItem[];
  requestsHasNext: boolean;
  requestsPage: number;
  requestsPageSize: number;
  requestsLoading: boolean;
  requestsError: unknown;
  requestFilter: string;
  onRequestFilterChange: (value: string) => void;
  onPreviousRequestPage: () => void;
  onNextRequestPage: () => void;
  onRetryRequests: () => void;
  records: UsageRecordResponse[];
  recordsLoading: boolean;
  recordsError: unknown;
  recordFilter: string;
  onRecordFilterChange: (value: string) => void;
  exportParams: ReturnType<typeof buildUsageParams> & { search?: string };
  recordsPage: number;
  recordsPageSize: number;
  recordsHasNext: boolean;
  onPreviousRecordPage: () => void;
  onNextRecordPage: () => void;
  onRetryRecords: () => void;
  onOpenRequestTrace: (request: GatewayRequestTraceListItem) => void;
  onOpenRecordTrace: (record: UsageRecordResponse) => void;
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Request traces</CardTitle>
          <Tabs value={activeTab} onValueChange={onActiveTabChange}>
            <TabsList>
              <TabsTrigger value="requests">Requests</TabsTrigger>
              <TabsTrigger value="attempts">Attempts</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs value={activeTab} onValueChange={onActiveTabChange}>
          <TabsContent value="requests" className="mt-0">
            <GatewayRequestsTable
              requests={requests}
              isLoading={requestsLoading}
              error={requestsError}
              filter={requestFilter}
              onFilterChange={onRequestFilterChange}
              page={requestsPage}
              pageSize={requestsPageSize}
              hasNext={requestsHasNext}
              onPreviousPage={onPreviousRequestPage}
              onNextPage={onNextRequestPage}
              onRetry={onRetryRequests}
              onOpenTrace={onOpenRequestTrace}
            />
          </TabsContent>
          <TabsContent value="attempts" className="mt-0">
            <UsageRecordsTable
              records={records}
              isLoading={recordsLoading}
              error={recordsError}
              filter={recordFilter}
              onFilterChange={onRecordFilterChange}
              exportParams={exportParams}
              page={recordsPage}
              pageSize={recordsPageSize}
              hasNext={recordsHasNext}
              onPreviousPage={onPreviousRecordPage}
              onNextPage={onNextRecordPage}
              onRetry={onRetryRecords}
              onOpenTrace={onOpenRecordTrace}
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function GatewayRequestsTable({
  requests,
  isLoading,
  error,
  filter,
  onFilterChange,
  page,
  pageSize,
  hasNext,
  onPreviousPage,
  onNextPage,
  onRetry,
  onOpenTrace,
}: {
  requests: GatewayRequestTraceListItem[];
  isLoading: boolean;
  error: unknown;
  filter: string;
  onFilterChange: (value: string) => void;
  page: number;
  pageSize: number;
  hasNext: boolean;
  onPreviousPage: () => void;
  onNextPage: () => void;
  onRetry: () => void;
  onOpenTrace: (request: GatewayRequestTraceListItem) => void;
}) {
  const startRequest = page * pageSize + 1;
  const endRequest = page * pageSize + requests.length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">Requests</div>
          <div className="text-xs text-muted-foreground">
            One row per gateway request, including fallback outcomes.
          </div>
        </div>
        <Input
          className="h-9 w-72"
          value={filter}
          onChange={(event) => onFilterChange(event.target.value)}
          placeholder="Search request, model, provider..."
        />
      </div>
      <DataTable<GatewayRequestTraceListItem>
        data={requests}
        loading={isLoading}
        error={error ? "Unable to load gateway requests." : undefined}
        onRetry={onRetry}
        getRowKey={(request) => request.id}
        empty={{
          icon: ChartNoAxesCombined,
          title: "No matching requests",
          description: "Gateway requests appear here as soon as proxy traffic is recorded.",
        }}
        columns={[
          {
            key: "time",
            header: "Time",
            className: "whitespace-nowrap text-muted-foreground",
            cell: (request) => new Date(request.started_at).toLocaleString(),
          },
          {
            key: "model",
            header: "Model",
            cell: (request) => (
              <>
                <div className="font-medium">{request.public_model_name ?? request.requested_model}</div>
                <div className="text-xs text-muted-foreground">
                  {request.final_provider_model ?? request.requested_model}
                </div>
              </>
            ),
          },
          {
            key: "provider",
            header: "Provider",
            cell: (request) => (
              <>
                <div className="font-medium">{request.final_provider_name ?? "Unresolved"}</div>
                <div className="text-xs text-muted-foreground">
                  {formatInvolvedProviders(request)}
                </div>
              </>
            ),
          },
          {
            key: "scope",
            header: "Scope",
            cell: (request) => (
              <>
                <div className="font-medium">{request.project_name ?? "No project"}</div>
                <div className="text-xs text-muted-foreground">{request.team_name ?? "No team"}</div>
              </>
            ),
          },
          {
            key: "status",
            header: "Status",
            cell: (request) => (
              <>
                {request.final_http_status == null ? (
                  <Badge variant="outline">Pending</Badge>
                ) : (
                  <HttpStatusBadge status={request.final_http_status} />
                )}
                <div className="mt-1 text-xs text-muted-foreground">{formatOutcome(request)}</div>
              </>
            ),
          },
          {
            key: "attempts",
            header: "Attempts",
            align: "right",
            cell: (request) => (
              <div>
                <div>{request.attempt_count.toLocaleString()}</div>
                {request.fallback_attempted ? (
                  <div className="text-xs text-muted-foreground">fallback</div>
                ) : null}
              </div>
            ),
          },
          {
            key: "duration",
            header: "Duration",
            align: "right",
            cell: (request) =>
              request.duration_ms == null ? (
                <span className="text-muted-foreground">Pending</span>
              ) : (
                `${request.duration_ms}ms`
              ),
          },
          {
            key: "trace",
            header: "Trace",
            align: "right",
            cell: (request) => (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Open request trace"
                onClick={() => onOpenTrace(request)}
              >
                <Eye />
              </Button>
            ),
          },
        ]}
        footer={
          requests.length > 0 ? (
            <>
              <span>
                Showing {startRequest.toLocaleString()}-{endRequest.toLocaleString()}
                {hasNext ? " of more requests" : ""}
              </span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={page === 0} onClick={onPreviousPage}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={!hasNext} onClick={onNextPage}>
                  Next
                </Button>
              </div>
            </>
          ) : undefined
        }
      />
    </div>
  );
}

function UsageRecordsTable({
  records,
  isLoading,
  error,
  filter,
  onFilterChange,
  exportParams,
  page,
  pageSize,
  hasNext,
  onPreviousPage,
  onNextPage,
  onRetry,
  onOpenTrace,
}: {
  records: UsageRecordResponse[];
  isLoading: boolean;
  error: unknown;
  filter: string;
  onFilterChange: (value: string) => void;
  exportParams: ReturnType<typeof buildUsageParams> & { search?: string };
  page: number;
  pageSize: number;
  hasNext: boolean;
  onPreviousPage: () => void;
  onNextPage: () => void;
  onRetry: () => void;
  onOpenTrace: (record: UsageRecordResponse) => void;
}) {
  const startRecord = page * pageSize + 1;
  const endRecord = page * pageSize + records.length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">Attempts</div>
          <div className="text-xs text-muted-foreground">
            Provider attempts that produced usage records.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            className="h-9 w-72"
            value={filter}
            onChange={(event) => onFilterChange(event.target.value)}
            placeholder="Search model, request, credential..."
          />
          <Button variant="outline" size="sm" onClick={() => downloadUsageExport(exportParams)}>
            <Download data-icon="inline-start" />
            Export CSV
          </Button>
        </div>
      </div>
      <DataTable<UsageRecordResponse>
        data={records}
        loading={isLoading}
        error={error ? "Unable to load usage records." : undefined}
        onRetry={onRetry}
        getRowKey={(record) => record.id}
        empty={{
          icon: ChartNoAxesCombined,
          title: "No matching usage records",
          description: "Usage appears here once virtual keys start serving requests.",
        }}
        columns={[
          {
            key: "time",
            header: "Time",
            className: "whitespace-nowrap text-muted-foreground",
            cell: (record) => new Date(record.created_at).toLocaleString(),
          },
          {
            key: "model",
            header: "Model",
            cell: (record) => (
              <>
                <div className="font-medium">{record.requested_model}</div>
                <div className="text-xs text-muted-foreground">{record.provider_model}</div>
              </>
            ),
          },
          {
            key: "credential",
            header: "Credential",
            cell: (record) => (
              <>
                <div className="font-medium">{record.provider_credential_name ?? "Unknown"}</div>
                <div className="font-mono text-xs text-muted-foreground">
                  {record.provider_credential_prefix ?? shortId(record.provider_credential_id)}
                </div>
              </>
            ),
          },
          {
            key: "request",
            header: "Request",
            cell: (record) => (
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">
                  {shortId(record.request_id)}
                </span>
                {record.gateway_request_id ? (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Open request trace"
                    onClick={() => onOpenTrace(record)}
                  >
                    <Eye />
                  </Button>
                ) : null}
              </div>
            ),
          },
          {
            key: "status",
            header: "Status",
            cell: (record) => (
              <>
                <HttpStatusBadge status={record.http_status} />
                {record.error_code ? (
                  <div className="mt-1 text-xs text-muted-foreground">{record.error_code}</div>
                ) : null}
              </>
            ),
          },
          {
            key: "tokens",
            header: "Tokens",
            align: "right",
            cell: (record) => (record.total_tokens ?? 0).toLocaleString(),
          },
          {
            key: "spend",
            header: "Spend",
            align: "right",
            cell: (record) => (
              <SpendCell
                confirmed={record.confirmed_spend_cents}
                estimated={record.estimated_spend_cents}
                unknown={record.spend_type === "unknown"}
              />
            ),
          },
          {
            key: "latency",
            header: "Latency",
            align: "right",
            cell: (record) => `${record.latency_ms}ms`,
          },
        ]}
        footer={
          records.length > 0 ? (
            <>
              <span>
                Showing {startRecord.toLocaleString()}-{endRecord.toLocaleString()}
                {hasNext ? " of more records" : ""}
              </span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={page === 0} onClick={onPreviousPage}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={!hasNext} onClick={onNextPage}>
                  Next
                </Button>
              </div>
            </>
          ) : undefined
        }
      />
    </div>
  );
}

function formatOutcome(request: GatewayRequestTraceListItem) {
  if (request.final_error_code) return request.final_error_code;
  if (request.outcome === "succeeded") return "Succeeded";
  if (request.outcome === "failed") return "Failed";
  if (request.outcome === "denied") return "Denied";
  return "Pending";
}

function formatInvolvedProviders(request: GatewayRequestTraceListItem) {
  const providers = request.involved_provider_names ?? [];
  if (providers.length === 0) return "No attempts";
  if (providers.length === 1) return providers[0];
  return `${providers[0]} +${providers.length - 1}`;
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
                    <span className="shrink-0 text-muted-foreground">{formatSpendParts(row)}</span>
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
            No active limit policies with budgets in their current intervals.
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
                        Current {row.interval} window
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

async function downloadUsageExport(
  params: ReturnType<typeof buildUsageParams> & { search?: string },
) {
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

function fillTimeSeriesGaps(
  points: UsageTimeSeriesPoint[],
  grain: UsageGrain,
  window: UsageWindow,
  customRangeEnabled: boolean,
  startDate: string,
  endDate: string,
) {
  if (points.length === 0) return points;
  const end = endDate ? new Date(`${endDate}T23:59:59`) : new Date();
  const firstPoint = new Date(points[0].bucket);
  const lastPoint = new Date(points[points.length - 1].bucket);
  const start =
    customRangeEnabled && startDate
      ? new Date(`${startDate}T00:00:00`)
      : windowStartDate(window, firstPoint);
  const rangeStart = window === "lifetime" && !startDate ? firstPoint : start;
  const rangeEnd = window === "lifetime" && !endDate ? lastPoint : end;
  const pointByBucket = new Map(
    points.map((point) => [bucketKey(new Date(point.bucket), grain), point]),
  );
  const filled: UsageTimeSeriesPoint[] = [];
  for (
    let cursor = alignBucket(rangeStart, grain);
    cursor <= rangeEnd;
    cursor = addBucket(cursor, grain)
  ) {
    const key = bucketKey(cursor, grain);
    filled.push(pointByBucket.get(key) ?? emptyTimeSeriesPoint(cursor));
  }
  return filled;
}

function windowStartDate(window: UsageWindow, fallback: Date) {
  const now = new Date();
  if (window === "24h") return new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (window === "7d") return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  if (window === "30d") return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  if (window === "90d") return new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
  return fallback;
}

function alignBucket(value: Date, grain: UsageGrain) {
  const next = new Date(value);
  next.setMinutes(0, 0, 0);
  if (grain !== "hour") next.setHours(0, 0, 0, 0);
  if (grain === "week") {
    const day = next.getDay();
    const offset = day === 0 ? 6 : day - 1;
    next.setDate(next.getDate() - offset);
  }
  return next;
}

function addBucket(value: Date, grain: UsageGrain) {
  const next = new Date(value);
  if (grain === "hour") next.setHours(next.getHours() + 1);
  if (grain === "day") next.setDate(next.getDate() + 1);
  if (grain === "week") next.setDate(next.getDate() + 7);
  return next;
}

function bucketKey(value: Date, grain: UsageGrain) {
  return alignBucket(value, grain).toISOString();
}

function emptyTimeSeriesPoint(bucket: Date): UsageTimeSeriesPoint {
  return {
    bucket: bucket.toISOString(),
    requests: 0,
    successful_requests: 0,
    failed_requests: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    cost_cents: 0,
    confirmed_spend_cents: 0,
    estimated_spend_cents: 0,
    unknown_usage_count: 0,
    unknown_total_tokens: 0,
    average_latency_ms: null,
    last_request_at: null,
  };
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

function UsageErrorAlert({
  title,
  error,
  fallback,
  onRetry,
}: {
  title: string;
  error: unknown;
  fallback: string;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span>{getProblemDetail(error, fallback)}</span>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
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
          <CardTitle>Recent proxy events</CardTitle>
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
  if (confirmed > 0) parts.push(`${formatCents(confirmed)} reported usage`);
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
