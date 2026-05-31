import { ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useListEventsApiV1GuardrailsEventsGet } from "@/shared/api/generated/guardrails/guardrails";
import type { GuardrailEventResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";

export function RecentGuardrailEventsCard({
  title = "Guardrail events",
  filters,
}: {
  title?: string;
  filters: {
    project_id?: string;
    virtual_key_id?: string;
  };
}) {
  const eventsQuery = useListEventsApiV1GuardrailsEventsGet({ ...filters, limit: 5 });
  const events = eventsQuery.data?.status === 200 ? eventsQuery.data.data : [];
  const activityHref = buildActivityHref(filters);

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Button asChild variant="outline" size="sm">
            <Link to={activityHref}>Open activity</Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {eventsQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading guardrail events...</p>
        ) : events.length === 0 ? (
          <EmptyState
            icon={ShieldAlert}
            title="No guardrail events"
            description="Denied and dry-run matches for this scope will appear here."
          />
        ) : (
          <div className="space-y-2">
            {events.map((event) => (
              <GuardrailEventRow key={event.id} event={event} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GuardrailEventRow({ event }: { event: GuardrailEventResponse }) {
  return (
    <div className="rounded-md border bg-background p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium">{event.reason.replaceAll("_", " ")}</div>
      <div className="mt-1 truncate text-xs text-muted-foreground">
        {event.requested_model ?? "-"} · {event.provider_model ?? "-"}
      </div>
      <div className="mt-1 font-mono text-xs text-muted-foreground">
        request {shortId(event.request_id)}
      </div>
        </div>
        <Badge variant={event.decision === "blocked" ? "destructive" : "outline"}>
          {event.decision === "dry_run" ? "Dry run" : event.decision}
        </Badge>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {new Date(event.created_at).toLocaleString()}
      </div>
    </div>
  );
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}

function buildActivityHref(filters: { project_id?: string; virtual_key_id?: string }) {
  const params = new URLSearchParams({ category: "guardrail" });
  if (filters.virtual_key_id) {
    params.set("entity_type", "virtual_key");
    params.set("entity_id", filters.virtual_key_id);
  } else if (filters.project_id) {
    params.set("entity_type", "project");
    params.set("entity_id", filters.project_id);
  }
  return `/activity?${params.toString()}`;
}
