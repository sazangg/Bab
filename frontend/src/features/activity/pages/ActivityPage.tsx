import {
  Activity,
  AlertTriangle,
  CalendarDays,
  Download,
  Eye,
  Info,
  Search,
  XCircle,
} from "lucide-react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { canViewActivity, hasPermission } from "@/features/auth/lib/permissions";
import { httpClient } from "@/shared/api/http-client";
import type {
  ActivityEventResponse,
  AuthenticatedUser,
  ProjectResponse,
  TeamResponse,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { EventDetailSheet, type EventDetailRow } from "@/shared/components/EventDetailSheet";
import { FilterToolbar, type FilterChip } from "@/shared/components/FilterToolbar";
import { PageHeader } from "@/shared/components/PageHeader";
import { RequestTraceSheet } from "@/features/usage/components/RequestTraceSheet";
import { buildDateRange, type DateRange } from "@/shared/lib/date-range";
import { downloadBlob } from "@/shared/lib/download";
import { shortId } from "@/shared/lib/short-id";
import { useDebouncedValue } from "@/shared/lib/use-debounced-value";

const ANY = "__any__";
const PAGE_SIZE = 50;
type ActivityScopeValue = "authorized" | `team:${string}` | `project:${string}`;
type ActivityParams = {
  category?: string;
  severity?: string;
  entity_type?: string;
  entity_id?: string;
  team_id?: string;
  project_id?: string;
  start_at?: string;
  end_at?: string;
  q?: string;
};

export function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const [category, setCategory] = useState(searchParams.get("category") ?? ANY);
  const [severity, setSeverity] = useState(searchParams.get("severity") ?? ANY);
  const [entityType, setEntityType] = useState(searchParams.get("entity_type") ?? ANY);
  const [entityId, setEntityId] = useState(searchParams.get("entity_id") ?? "");
  const [startDate, setStartDate] = useState(searchParams.get("start") ?? "");
  const [endDate, setEndDate] = useState(searchParams.get("end") ?? "");
  const [customRangeEnabled, setCustomRangeEnabled] = useState(
    Boolean(searchParams.get("start") || searchParams.get("end")),
  );
  const [scopeValue, setScopeValue] = useState<ActivityScopeValue>("authorized");
  const [entitySearch, setEntitySearch] = useState(searchParams.get("q") ?? "");
  const debouncedSearch = useDebouncedValue(entitySearch, 300);
  const [selectedEvent, setSelectedEvent] = useState<ActivityEventResponse | null>(null);
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canViewOrgActivity = hasPermission(currentUser, "activity.view");
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const activityScopes = buildActivityScopes({
    canViewOrgActivity,
    teams,
    projects,
    currentUser,
  });
  const selectedActivityScope = activityScopes.some((scope) => scope.value === scopeValue)
    ? scopeValue
    : "authorized";
  const dateRange: DateRange = customRangeEnabled ? buildDateRange(startDate, endDate) : {};
  const activityParams: ActivityParams = {
    category: category === ANY ? undefined : category,
    severity: severity === ANY ? undefined : severity,
    entity_type: entityType === ANY ? undefined : entityType,
    entity_id: entityType === ANY || !entityId.trim() ? undefined : entityId.trim(),
    start_at: dateRange.startAt,
    end_at: dateRange.endAt,
    q: debouncedSearch.trim() || undefined,
    ...buildActivityScopeParams(canViewOrgActivity ? "authorized" : selectedActivityScope),
  };
  const activityQuery = useInfiniteQuery({
    queryKey: ["activity-events", activityParams],
    enabled: !dateRange.error,
    initialPageParam: undefined as ActivityCursor | undefined,
    queryFn: async ({ pageParam }) => {
      const response = await httpClient.get<ActivityEventResponse[]>("/api/v1/activity", {
        params: {
          ...activityParams,
          limit: PAGE_SIZE,
          before_at: pageParam?.beforeAt,
          before_id: pageParam?.beforeId,
        },
      });
      return response.data;
    },
    getNextPageParam: (page) => {
      if (page.length < PAGE_SIZE) return undefined;
      const last = page.at(-1);
      return last ? { beforeAt: last.created_at, beforeId: last.id } : undefined;
    },
  });
  const events = activityQuery.data?.pages.flat() ?? [];
  useEffect(() => {
    updateSearchParam(setSearchParams, "q", debouncedSearch);
  }, [debouncedSearch, setSearchParams]);
  const updateFilter = (updates: Record<string, string>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (!value || value === ANY) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };
  const clearFilters = () => {
    setCategory(ANY);
    setSeverity(ANY);
    setEntityType(ANY);
    setEntityId("");
    setStartDate("");
    setEndDate("");
    setCustomRangeEnabled(false);
    setScopeValue("authorized");
    setEntitySearch("");
    setSearchParams({}, { replace: true });
  };

  if (currentUserQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Checking activity access...</p>;
  }

  if (!canViewActivity(currentUser)) {
    return (
      <EmptyState
        icon={Activity}
        title="No activity access"
        description="Your account does not have an organization, team, or project activity scope."
      />
    );
  }

  const chips: FilterChip[] = [];
  if (!canViewOrgActivity && selectedActivityScope !== "authorized") {
    const scopeLabel = activityScopes.find((scope) => scope.value === selectedActivityScope)?.label;
    chips.push({
      key: "scope",
      label: `Scope: ${scopeLabel ?? selectedActivityScope}`,
      onRemove: () => setScopeValue("authorized"),
    });
  }
  if (entitySearch.trim()) {
    chips.push({
      key: "q",
      label: `Search: ${entitySearch.trim()}`,
      onRemove: () => setEntitySearch(""),
    });
  }
  if (category !== ANY) {
    chips.push({
      key: "category",
      label: `Category: ${category}`,
      onRemove: () => {
        setCategory(ANY);
        updateFilter({ category: ANY });
      },
    });
  }
  if (severity !== ANY) {
    chips.push({
      key: "severity",
      label: `Severity: ${severity}`,
      onRemove: () => {
        setSeverity(ANY);
        updateFilter({ severity: ANY });
      },
    });
  }
  if (entityType !== ANY) {
    chips.push({
      key: "entity",
      label: entityId.trim()
        ? `Entity: ${entityType} ${shortId(entityId.trim())}`
        : `Entity: ${entityType}`,
      onRemove: () => {
        setEntityType(ANY);
        setEntityId("");
        updateFilter({ entity_type: ANY, entity_id: "" });
      },
    });
  }
  if (customRangeEnabled && (startDate || endDate)) {
    chips.push({
      key: "dates",
      label: `Date: ${startDate || "…"} – ${endDate || "…"}`,
      onRemove: () => {
        setStartDate("");
        setEndDate("");
        setCustomRangeEnabled(false);
        updateFilter({ start: "", end: "" });
      },
    });
  }

  const columns: DataTableColumn<ActivityEventResponse>[] = [
    {
      key: "event",
      header: "Event",
      className: "max-w-[28rem] whitespace-normal",
      cell: (event) => {
        const Icon =
          event.severity === "error"
            ? XCircle
            : event.severity === "warning"
              ? AlertTriangle
              : Info;
        return (
          <div className="flex gap-2">
            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="font-medium">{event.message}</div>
              <div className="mt-1 text-xs text-muted-foreground">{event.action}</div>
            </div>
          </div>
        );
      },
    },
    {
      key: "category",
      header: "Category",
      cell: (event) => (
        <div className="flex items-center gap-1.5">
          <Badge variant="outline">{event.category}</Badge>
          <Badge variant={event.severity === "error" ? "destructive" : "secondary"}>
            {event.severity}
          </Badge>
        </div>
      ),
    },
    {
      key: "actor",
      header: "Actor",
      cell: (event) => event.actor_email ?? "Gateway runtime",
    },
    {
      key: "context",
      header: "Context",
      className: "max-w-[18rem] whitespace-normal text-xs text-muted-foreground",
      cell: (event) => (
        <div className="flex items-center gap-2">
          <span>{contextLabel(event)}</span>
          {event.gateway_request_id ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Open request trace"
              onClick={(clickEvent) => {
                clickEvent.stopPropagation();
                setTraceRequestId(event.gateway_request_id);
              }}
            >
              <Eye />
            </Button>
          ) : null}
        </div>
      ),
    },
    {
      key: "time",
      header: "Time",
      align: "right",
      className: "text-muted-foreground",
      cell: (event) => new Date(event.created_at).toLocaleString(),
    },
  ];

  const detailRows: EventDetailRow[] = selectedEvent
    ? [
        { label: "Event", value: selectedEvent.message },
        { label: "Action", value: selectedEvent.action },
        { label: "Category", value: selectedEvent.category },
        { label: "Severity", value: selectedEvent.severity },
        { label: "Actor", value: selectedEvent.actor_email ?? "Gateway runtime" },
        { label: "Time", value: new Date(selectedEvent.created_at).toLocaleString() },
        { label: "Event ID", value: selectedEvent.id, mono: true },
        { label: "Request ID", value: selectedEvent.request_id ?? "-", mono: true },
      ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Activity"
        description={
          canViewOrgActivity
            ? "Recent admin changes and runtime gateway denials across the organization."
            : "Recent activity for your authorized teams and directly administered projects."
        }
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={isExporting || Boolean(dateRange.error)}
            onClick={async () => {
              setIsExporting(true);
              try {
                await downloadActivityExport(activityParams);
                toast.success("Activity export downloaded.");
              } catch {
                toast.error("Activity export could not be downloaded.");
              } finally {
                setIsExporting(false);
              }
            }}
          >
            <Download data-icon="inline-start" />
            {isExporting ? "Exporting..." : "Export CSV"}
          </Button>
        }
      />
      <Card>
        <CardHeader className="border-b">
          <CardTitle>Recent events</CardTitle>
          <FilterToolbar
            className="mt-3"
            chips={chips}
            onClearAll={chips.length > 0 ? clearFilters : undefined}
          >
            {!canViewOrgActivity ? (
              <ScopeSelect
                value={selectedActivityScope}
                scopes={activityScopes}
                onChange={setScopeValue}
              />
            ) : null}
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={entitySearch}
                onChange={(event) => setEntitySearch(event.target.value)}
                placeholder="Filter entity, actor, metadata..."
              />
            </div>
            <Select
              value={category}
              onValueChange={(value) => {
                setCategory(value);
                updateFilter({ category: value });
              }}
            >
              <SelectTrigger aria-label="Filter by category" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={ANY}>All categories</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="workspace">Workspace</SelectItem>
                  <SelectItem value="settings">Settings</SelectItem>
                  <SelectItem value="policy">Policy</SelectItem>
                  <SelectItem value="guardrail">Guardrail</SelectItem>
                  <SelectItem value="proxy">Proxy</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={severity}
              onValueChange={(value) => {
                setSeverity(value);
                updateFilter({ severity: value });
              }}
            >
              <SelectTrigger aria-label="Filter by severity" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={ANY}>All severities</SelectItem>
                  <SelectItem value="info">Info</SelectItem>
                  <SelectItem value="warning">Warning</SelectItem>
                  <SelectItem value="error">Error</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={entityType}
              onValueChange={(value) => {
                setEntityType(value);
                const nextEntityId = value === ANY ? "" : entityId;
                if (value === ANY) setEntityId("");
                updateFilter({ entity_type: value, entity_id: nextEntityId });
              }}
            >
              <SelectTrigger aria-label="Filter by entity type" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={ANY}>All entities</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="virtual_key">Virtual key</SelectItem>
                  <SelectItem value="pool">Pool</SelectItem>
                  <SelectItem value="model_offering">Model offering</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Input
              className="w-full font-mono xl:w-64"
              value={entityId}
              disabled={entityType === ANY}
              onChange={(event) => {
                setEntityId(event.target.value);
                updateFilter({ entity_id: event.target.value });
              }}
              placeholder="Entity id"
            />
            <DateRangePopover
              startDate={startDate}
              endDate={endDate}
              enabled={customRangeEnabled}
              onStartDateChange={(value) => {
                setStartDate(value);
                updateFilter({ start: value });
              }}
              onEndDateChange={(value) => {
                setEndDate(value);
                updateFilter({ end: value });
              }}
              onApply={() => setCustomRangeEnabled(Boolean(startDate || endDate))}
              onClear={() => {
                setStartDate("");
                setEndDate("");
                setCustomRangeEnabled(false);
                updateFilter({ start: "", end: "" });
              }}
            />
          </FilterToolbar>
        </CardHeader>
        <CardContent>
          {dateRange.error ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>Invalid date range</AlertTitle>
              <AlertDescription>{dateRange.error}</AlertDescription>
            </Alert>
          ) : (
            <>
              <DataTable
                columns={columns}
                data={events}
                loading={activityQuery.isPending}
                error={activityQuery.isError ? "Activity could not be loaded." : undefined}
                onRetry={() => void activityQuery.refetch()}
                getRowKey={(event) => event.id}
                onRowClick={setSelectedEvent}
                empty={{
                  icon: Activity,
                  title: "No activity yet",
                  description:
                    "Admin changes and proxy denials matching the filters will appear here.",
                }}
              />
              {activityQuery.hasNextPage ? (
                <div className="flex justify-center pt-4">
                  <Button
                    variant="outline"
                    disabled={activityQuery.isFetchingNextPage}
                    onClick={() => activityQuery.fetchNextPage()}
                  >
                    {activityQuery.isFetchingNextPage ? "Loading..." : "Load more"}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <EventDetailSheet
        open={Boolean(selectedEvent)}
        onOpenChange={(open) => !open && setSelectedEvent(null)}
        title="Activity event details"
        description="Severity, actor, context, and metadata for this event."
        rows={detailRows}
        json={
          selectedEvent
            ? { context: eventContext(selectedEvent), metadata: selectedEvent.metadata }
            : undefined
        }
      />
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
  const label = enabled ? `${startDate || "Start"} - ${endDate || "Today"}` : "Date range";
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

function ScopeSelect({
  value,
  scopes,
  onChange,
}: {
  value: ActivityScopeValue;
  scopes: ActivityScopeOption[];
  onChange: (value: ActivityScopeValue) => void;
}) {
  return (
    <Select value={value} onValueChange={(nextValue) => onChange(nextValue as ActivityScopeValue)}>
      <SelectTrigger aria-label="Filter by scope" className="w-52">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {scopes.map((scope) => (
            <SelectItem key={scope.value} value={scope.value}>
              {scope.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function contextLabel(event: ActivityEventResponse) {
  const parts = Object.entries(eventContext(event)).map(
    ([key, value]) => `${labelize(key)} ${shortId(value)}`,
  );
  return parts.length > 0 ? parts.join(" · ") : "-";
}

function eventContext(event: ActivityEventResponse) {
  return Object.fromEntries(
    Object.entries({
      provider: event.provider_id,
      team: event.team_id,
      project: event.project_id,
      virtual_key: event.virtual_key_id,
      pool: event.pool_id,
      model_offering: event.model_offering_id,
    }).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}

function labelize(value: string) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

type ActivityScopeOption = {
  value: ActivityScopeValue;
  label: string;
};

type ActivityCursor = {
  beforeAt: string;
  beforeId: string;
};

function buildActivityScopes({
  canViewOrgActivity,
  teams,
  projects,
  currentUser,
}: {
  canViewOrgActivity: boolean;
  teams: TeamResponse[];
  projects: ProjectResponse[];
  currentUser: AuthenticatedUser | null;
}): ActivityScopeOption[] {
  if (canViewOrgActivity) {
    return [{ value: "authorized", label: "Organization" }];
  }
  const teamById = Object.fromEntries(teams.map((team) => [team.id, team]));
  const projectById = Object.fromEntries(projects.map((project) => [project.id, project]));
  const options: ActivityScopeOption[] = [
    { value: "authorized", label: "All authorized activity" },
  ];
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

function dedupeScopes(options: ActivityScopeOption[]) {
  const seen = new Set<ActivityScopeValue>();
  return options.filter((option) => {
    if (seen.has(option.value)) return false;
    seen.add(option.value);
    return true;
  });
}

function buildActivityScopeParams(scopeValue: ActivityScopeValue) {
  const params: {
    team_id?: string;
    project_id?: string;
  } = {};
  if (scopeValue.startsWith("team:")) {
    params.team_id = scopeValue.slice("team:".length);
  }
  if (scopeValue.startsWith("project:")) {
    params.project_id = scopeValue.slice("project:".length);
  }
  return params;
}

async function downloadActivityExport(
  params: ReturnType<typeof buildActivityScopeParams> & {
    category?: string;
    severity?: string;
    entity_type?: string;
    entity_id?: string;
    start_at?: string;
    end_at?: string;
    q?: string;
  },
) {
  const response = await httpClient.get<Blob>("/api/v1/activity/export", {
    params,
    responseType: "blob",
  });
  downloadBlob(response.data, "bab-activity-events.csv");
}

function updateSearchParam(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  key: string,
  value: string,
) {
  setSearchParams(
    (current) => {
      const next = new URLSearchParams(current);
      if (value.trim()) next.set(key, value.trim());
      else next.delete(key);
      return next;
    },
    { replace: true },
  );
}
