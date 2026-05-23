import { Activity, AlertTriangle, Info, XCircle } from "lucide-react";
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
import { useListActivityEventsApiV1ActivityGet } from "@/shared/api/generated/activity/activity";
import type { ActivityEventResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

const ANY = "__any__";

export function ActivityPage() {
  const [category, setCategory] = useState(ANY);
  const [severity, setSeverity] = useState(ANY);
  const activityQuery = useListActivityEventsApiV1ActivityGet({
    limit: 100,
    category: category === ANY ? undefined : category,
    severity: severity === ANY ? undefined : severity,
  });
  const events = activityQuery.data?.status === 200 ? activityQuery.data.data : [];

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
            <div className="flex gap-2">
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>All categories</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="workspace">Workspace</SelectItem>
                  <SelectItem value="allocation">Allocation</SelectItem>
                  <SelectItem value="proxy">Proxy</SelectItem>
                </SelectContent>
              </Select>
              <Select value={severity} onValueChange={setSeverity}>
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
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {activityQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading activity...</p>
          ) : events.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="No activity yet"
              description="Admin changes and proxy denials will appear here."
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
                {events.map((event) => (
                  <ActivityRow key={event.id} event={event} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ActivityRow({ event }: { event: ActivityEventResponse }) {
  const Icon =
    event.severity === "error" ? XCircle : event.severity === "warning" ? AlertTriangle : Info;
  return (
    <TableRow>
      <TableCell className="max-w-[28rem] whitespace-normal">
        <div className="flex gap-2">
          <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
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
  );
}

function contextLabel(event: ActivityEventResponse) {
  const parts = [
    event.provider_id ? `Provider ${shortId(event.provider_id)}` : null,
    event.team_id ? `Team ${shortId(event.team_id)}` : null,
    event.project_id ? `Project ${shortId(event.project_id)}` : null,
    event.allocation_id ? `Allocation ${shortId(event.allocation_id)}` : null,
    event.virtual_key_id ? `Key ${shortId(event.virtual_key_id)}` : null,
    event.pool_id ? `Pool ${shortId(event.pool_id)}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "-";
}

function shortId(value: string) {
  return value.slice(0, 8);
}
