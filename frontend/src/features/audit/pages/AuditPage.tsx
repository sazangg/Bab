import { Activity, ChevronRight } from "lucide-react";
import { useState } from "react";

import { useListAuditLogsApiV1AuditLogsGet } from "@/shared/api/generated/audit-logs/audit-logs";
import type { AuditEvent } from "@/shared/api/generated/schemas";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

export function AuditPage() {
  const auditQuery = useListAuditLogsApiV1AuditLogsGet({ limit: 100 });
  const events = auditQuery.data?.status === 200 ? auditQuery.data.data : [];

  return (
    <>
      <PageHeader title="Audit log" description="Management-plane events: who changed what." />
      {auditQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading audit log...</p>
      ) : events.length === 0 ? (
        <EmptyState
          icon={Activity}
          title="No audit events yet"
          description="Auditable actions like creating a provider or revoking a key will appear here."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[1%]" />
                <TableHead>Time</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <AuditRow key={event.id} event={event} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const hasMetadata =
    event.event_metadata && Object.keys(event.event_metadata as Record<string, unknown>).length > 0;

  return (
    <>
      <TableRow className="cursor-pointer" onClick={() => setOpen((value) => !value)}>
        <TableCell className="w-[1%]">
          <ChevronRight
            className={`size-3.5 text-muted-foreground transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </TableCell>
        <TableCell className="text-muted-foreground tabular-nums">
          {new Date(event.created_at).toLocaleString()}
        </TableCell>
        <TableCell className="font-mono text-xs">{event.event}</TableCell>
        <TableCell className="text-muted-foreground">
          {event.target_type ? (
            <>
              {event.target_type}
              {event.target_id ? ` · ${event.target_id.slice(0, 8)}` : ""}
            </>
          ) : (
            "—"
          )}
        </TableCell>
        <TableCell className="text-muted-foreground">
          {event.actor_user_id ? event.actor_user_id.slice(0, 8) : "system"}
        </TableCell>
        <TableCell className="text-muted-foreground">{event.ip_address ?? "—"}</TableCell>
      </TableRow>
      {open ? (
        <TableRow className="bg-muted/30">
          <TableCell />
          <TableCell colSpan={5}>
            {hasMetadata ? (
              <pre className="overflow-auto rounded-md border bg-background p-3 text-xs">
                {JSON.stringify(event.event_metadata, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-muted-foreground">No metadata recorded.</p>
            )}
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}
