import { ClipboardList, Download, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useListAuditEventsApiV1AuthAuditGet } from "@/shared/api/generated/auth/auth";
import { httpClient } from "@/shared/api/http-client";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

export function AuditPage() {
  const [filter, setFilter] = useState("");
  const auditQuery = useListAuditEventsApiV1AuthAuditGet({ limit: 200 });
  const events = useMemo(
    () => (auditQuery.data?.status === 200 ? auditQuery.data.data : []),
    [auditQuery.data],
  );
  const filteredEvents = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return events;
    return events.filter((event) =>
      `${event.actor_email ?? ""} ${event.actor_role ?? ""} ${event.action} ${event.entity_type} ${event.entity_id ?? ""}`
        .toLowerCase()
        .includes(term),
    );
  }, [events, filter]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit"
        description="Mutation-grade actor trail for organization administration."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-80">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter actor, action, entity..."
              />
            </div>
            <Button variant="outline" size="sm" onClick={downloadAuditExport}>
              <Download data-icon="inline-start" />
              Export CSV
            </Button>
            <Button variant="outline" size="sm" onClick={verifyAuditChain}>
              <ShieldCheck data-icon="inline-start" />
              Verify chain
            </Button>
          </div>
        }
      />

      <Card>
        <CardHeader className="border-b">
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Audit events</CardTitle>
            <Badge variant="outline">{filteredEvents.length}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {auditQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading audit events...</p>
          ) : filteredEvents.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No audit events"
              description="Administrative mutations will appear here with actor and entity context."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead>Metadata</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredEvents.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {new Date(event.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{event.actor_email ?? "System"}</div>
                      {event.actor_role ? (
                        <div className="text-xs text-muted-foreground">{event.actor_role}</div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{event.action}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{event.entity_type}</div>
                      {event.entity_id ? (
                        <div className="max-w-48 truncate font-mono text-xs text-muted-foreground">
                          {event.entity_id}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="max-w-80 truncate font-mono text-xs text-muted-foreground">
                      {formatMetadata(event.metadata)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function formatMetadata(metadata: Record<string, unknown>) {
  const keys = Object.keys(metadata);
  if (keys.length === 0) return "-";
  return JSON.stringify(metadata);
}

async function downloadAuditExport() {
  const response = await httpClient.get<Blob>("/api/v1/auth/audit/export", {
    responseType: "blob",
  });
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-audit-events.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function verifyAuditChain() {
  const response = await httpClient.get<{
    valid: boolean;
    checked_events: number;
    reason: string | null;
  }>("/api/v1/auth/audit/verify");
  if (response.data.valid) {
    toast.success(`Audit chain verified (${response.data.checked_events} events).`);
    return;
  }
  toast.error(response.data.reason ?? "Audit chain verification failed.");
}
