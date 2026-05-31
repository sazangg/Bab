import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
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
import type { ActivityEventResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

const ANY = "__any__";

export function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [category, setCategory] = useState(searchParams.get("category") ?? ANY);
  const [severity, setSeverity] = useState(searchParams.get("severity") ?? ANY);
  const [entityType, setEntityType] = useState(searchParams.get("entity_type") ?? ANY);
  const [entityId, setEntityId] = useState(searchParams.get("entity_id") ?? "");
  const [entitySearch, setEntitySearch] = useState(searchParams.get("q") ?? "");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const activityQuery = useListActivityEventsApiV1ActivityGet({
    limit: 100,
    category: category === ANY ? undefined : category,
    severity: severity === ANY ? undefined : severity,
    entity_type: entityType === ANY ? undefined : entityType,
    entity_id: entityType === ANY || !entityId.trim() ? undefined : entityId.trim(),
  });
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
    setEntitySearch("");
    setSearchParams({}, { replace: true });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="Recent admin changes and runtime gateway denials for super-admin operators."
      />
      <Card>
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Recent events</CardTitle>
            <div className="flex flex-wrap gap-2">
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
                  <SelectItem value="allocation">Allocation</SelectItem>
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
                  <SelectItem value="allocation">Allocation</SelectItem>
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
      allocation: event.allocation_id,
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
