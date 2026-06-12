import {
  Activity,
  AlertTriangle,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Download,
  Info,
  Search,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

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
import { useListActivityEventsApiV1ActivityGet } from "@/shared/api/generated/activity/activity";
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
import { PageHeader } from "@/shared/components/PageHeader";

const ANY = "__any__";
type ActivityScopeValue = "authorized" | `team:${string}` | `project:${string}`;

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
  const [expandedId, setExpandedId] = useState<string | null>(null);
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
  const activityParams = {
    limit: 100,
    category: category === ANY ? undefined : category,
    severity: severity === ANY ? undefined : severity,
    entity_type: entityType === ANY ? undefined : entityType,
    entity_id: entityType === ANY || !entityId.trim() ? undefined : entityId.trim(),
    start_at:
      customRangeEnabled && startDate ? new Date(`${startDate}T00:00:00`).toISOString() : undefined,
    end_at:
      customRangeEnabled && endDate ? new Date(`${endDate}T23:59:59`).toISOString() : undefined,
    ...buildActivityScopeParams(canViewOrgActivity ? "authorized" : selectedActivityScope),
  };
  const activityQuery = useListActivityEventsApiV1ActivityGet(activityParams);
  const events = activityQuery.data?.status === 200 ? activityQuery.data.data : [];
  const filteredEvents = events.filter((event) => {
    const term = entitySearch.trim().toLowerCase();
    if (!term) return true;
    return `${event.message} ${event.action} ${event.actor_email ?? ""} ${event.request_id ?? ""} ${contextLabel(event)} ${JSON.stringify(event.metadata)}`
      .toLowerCase()
      .includes(term);
  });
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description={
          canViewOrgActivity
            ? "Recent admin changes and runtime gateway denials across the organization."
            : "Recent activity for your authorized teams and directly administered projects."
        }
      />
      <Card>
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Recent events</CardTitle>
            <div className="flex flex-wrap gap-2">
              {!canViewOrgActivity ? (
                <ScopeSelect
                  value={selectedActivityScope}
                  scopes={activityScopes}
                  onChange={setScopeValue}
                />
              ) : null}
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-9 w-64 pl-9"
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
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>All categories</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="workspace">Workspace</SelectItem>
                  <SelectItem value="settings">Settings</SelectItem>
                  <SelectItem value="guardrail">Guardrail</SelectItem>
                  <SelectItem value="proxy">Proxy</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={severity}
                onValueChange={(value) => {
                  setSeverity(value);
                  updateFilter({ severity: value });
                }}
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>All severities</SelectItem>
                  <SelectItem value="info">Info</SelectItem>
                  <SelectItem value="warning">Warning</SelectItem>
                  <SelectItem value="error">Error</SelectItem>
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
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>All entities</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="virtual_key">Virtual key</SelectItem>
                  <SelectItem value="pool">Pool</SelectItem>
                  <SelectItem value="model_offering">Model offering</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="h-9 w-72 font-mono"
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
              <Button
                type="button"
                variant="outline"
                onClick={() => downloadActivityExport(activityParams)}
              >
                <Download data-icon="inline-start" />
                Export CSV
              </Button>
              <Button type="button" variant="outline" onClick={clearFilters}>
                Clear
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {activityQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading activity...</p>
          ) : filteredEvents.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="No activity yet"
              description="Admin changes and proxy denials matching the filters will appear here."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Event</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Context</TableHead>
                  <TableHead className="text-right">Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredEvents.map((event) => (
                  <ActivityRow
                    key={event.id}
                    event={event}
                    expanded={expandedId === event.id}
                    onToggle={() =>
                      setExpandedId((current) => (current === event.id ? null : event.id))
                    }
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
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
      <SelectTrigger className="w-52">
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
  );
}

function ActivityRow({
  event,
  expanded,
  onToggle,
}: {
  event: ActivityEventResponse;
  expanded: boolean;
  onToggle: () => void;
}) {
  const Icon =
    event.severity === "error" ? XCircle : event.severity === "warning" ? AlertTriangle : Info;
  return (
    <>
      <TableRow>
        <TableCell className="max-w-[28rem] whitespace-normal">
          <div className="flex gap-2">
            <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={onToggle}>
              {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            </Button>
            <Icon className="mt-1 size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="font-medium">{event.message}</div>
              <div className="mt-1 text-xs text-muted-foreground">{event.action}</div>
            </div>
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <Badge variant="outline">{event.category}</Badge>
            <Badge variant={event.severity === "error" ? "destructive" : "secondary"}>
              {event.severity}
            </Badge>
          </div>
        </TableCell>
        <TableCell>{event.actor_email ?? "Gateway runtime"}</TableCell>
        <TableCell className="max-w-[18rem] whitespace-normal text-xs text-muted-foreground">
          {contextLabel(event)}
        </TableCell>
        <TableCell className="text-right text-muted-foreground">
          {new Date(event.created_at).toLocaleString()}
        </TableCell>
      </TableRow>
      {expanded ? (
        <TableRow>
          <TableCell colSpan={5} className="bg-muted/20">
            <pre className="max-h-64 overflow-auto rounded-md bg-background p-3 text-xs">
              {JSON.stringify(
                {
                  id: event.id,
                  context: eventContext(event),
                  request_id: event.request_id,
                  metadata: event.metadata,
                },
                null,
                2,
              )}
            </pre>
          </TableCell>
        </TableRow>
      ) : null}
    </>
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

function shortId(value: string) {
  return value.slice(0, 8);
}

type ActivityScopeOption = {
  value: ActivityScopeValue;
  label: string;
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
  const options: ActivityScopeOption[] = [{ value: "authorized", label: "All authorized activity" }];
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

async function downloadActivityExport(params: ReturnType<typeof buildActivityScopeParams> & {
  limit?: number;
  category?: string;
  severity?: string;
  entity_type?: string;
  entity_id?: string;
  start_at?: string;
  end_at?: string;
}) {
  const exportParams = { ...params };
  delete exportParams.limit;
  const response = await httpClient.get<Blob>("/api/v1/activity/export", {
    params: exportParams,
    responseType: "blob",
  });
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-activity-events.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}
