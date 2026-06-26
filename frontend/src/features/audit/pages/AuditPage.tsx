import { useInfiniteQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, Search, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { httpClient } from "@/shared/api/http-client";
import type { AuditEventResponse, AuditVerificationResponse } from "@/shared/api/generated/schemas";
import { EventDetailSheet, type EventDetailRow } from "@/shared/components/EventDetailSheet";
import { FilterToolbar, type FilterChip } from "@/shared/components/FilterToolbar";
import { PageHeader } from "@/shared/components/PageHeader";
import { buildDateRange } from "@/shared/lib/date-range";
import { downloadBlob } from "@/shared/lib/download";
import { shortId } from "@/shared/lib/short-id";
import { useDebouncedValue } from "@/shared/lib/use-debounced-value";

const ANY = "__any__";
const PAGE_SIZE = 50;

type AuditParams = {
  start_at?: string;
  end_at?: string;
  actor_user_id?: string;
  action?: string;
  entity_type?: string;
  entity_id?: string;
  q?: string;
};

type AuditCursor = {
  beforeAt: string;
  beforeId: string;
};

export function AuditPage() {
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [action, setAction] = useState("");
  const [actorUserId, setActorUserId] = useState("");
  const [entityType, setEntityType] = useState(ANY);
  const [entityId, setEntityId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedEvent, setSelectedEvent] = useState<AuditEventResponse | null>(null);
  const [verification, setVerification] = useState<AuditVerificationResponse | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const dateRange = buildDateRange(startDate, endDate);
  const params: AuditParams = {
    q: debouncedSearch.trim() || undefined,
    action: action.trim() || undefined,
    actor_user_id: actorUserId.trim() || undefined,
    entity_type: entityType === ANY ? undefined : entityType,
    entity_id: entityType === ANY || !entityId.trim() ? undefined : entityId.trim(),
    start_at: dateRange.startAt,
    end_at: dateRange.endAt,
  };
  const auditQuery = useInfiniteQuery({
    queryKey: ["audit-events", params],
    enabled: !dateRange.error,
    initialPageParam: undefined as AuditCursor | undefined,
    queryFn: async ({ pageParam }) => {
      const response = await httpClient.get<AuditEventResponse[]>("/api/v1/audit", {
        params: {
          ...params,
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
  const events = auditQuery.data?.pages.flat() ?? [];

  const clearFilters = () => {
    setSearch("");
    setAction("");
    setActorUserId("");
    setEntityType(ANY);
    setEntityId("");
    setStartDate("");
    setEndDate("");
  };

  const downloadExport = async () => {
    setIsExporting(true);
    try {
      const response = await httpClient.get<Blob>("/api/v1/audit/export", {
        params,
        responseType: "blob",
      });
      downloadBlob(response.data, "bab-audit-events.csv");
      toast.success("Audit export downloaded.");
    } catch {
      toast.error("Audit export could not be downloaded.");
    } finally {
      setIsExporting(false);
    }
  };

  const verifyChain = async () => {
    setIsVerifying(true);
    try {
      const response = await httpClient.get<AuditVerificationResponse>("/api/v1/audit/verify");
      setVerification(response.data);
      if (response.data.valid) {
        toast.success(`Audit chain verified (${response.data.checked_events} events).`);
      } else {
        toast.error(response.data.reason ?? "Audit chain verification failed.");
      }
    } catch {
      toast.error("Audit chain verification could not be completed.");
    } finally {
      setIsVerifying(false);
    }
  };

  const chips: FilterChip[] = [];
  if (search.trim()) {
    chips.push({ key: "q", label: `Search: ${search.trim()}`, onRemove: () => setSearch("") });
  }
  if (action.trim()) {
    chips.push({ key: "action", label: `Action: ${action.trim()}`, onRemove: () => setAction("") });
  }
  if (actorUserId.trim()) {
    chips.push({
      key: "actor",
      label: `Actor: ${shortId(actorUserId.trim())}`,
      onRemove: () => setActorUserId(""),
    });
  }
  if (entityType !== ANY) {
    chips.push({
      key: "entity",
      label: entityId.trim() ? `Entity: ${entityType} ${shortId(entityId.trim())}` : `Entity: ${entityType}`,
      onRemove: () => {
        setEntityType(ANY);
        setEntityId("");
      },
    });
  }
  if (startDate || endDate) {
    chips.push({
      key: "dates",
      label: `Date: ${startDate || "…"} – ${endDate || "…"}`,
      onRemove: () => {
        setStartDate("");
        setEndDate("");
      },
    });
  }

  const columns: DataTableColumn<AuditEventResponse>[] = [
    {
      key: "time",
      header: "Time",
      className: "whitespace-nowrap text-muted-foreground",
      cell: (event) => new Date(event.created_at).toLocaleString(),
    },
    {
      key: "actor",
      header: "Actor",
      cell: (event) => (
        <>
          <div className="font-medium">{event.actor_email ?? "System"}</div>
          {event.actor_role ? (
            <div className="text-xs text-muted-foreground">{event.actor_role}</div>
          ) : null}
        </>
      ),
    },
    {
      key: "action",
      header: "Action",
      cell: (event) => <Badge variant="secondary">{event.action}</Badge>,
    },
    {
      key: "entity",
      header: "Entity",
      cell: (event) => (
        <>
          <div className="font-medium">{event.entity_type}</div>
          {event.entity_id ? (
            <div className="max-w-48 truncate font-mono text-xs text-muted-foreground">
              {event.entity_id}
            </div>
          ) : null}
        </>
      ),
    },
    {
      key: "metadata",
      header: "Metadata",
      className: "max-w-80 truncate font-mono text-xs text-muted-foreground",
      cell: (event) => formatMetadata(event.metadata),
    },
  ];

  const detailRows: EventDetailRow[] = selectedEvent
    ? [
        { label: "Event ID", value: selectedEvent.id, mono: true },
        { label: "Created", value: new Date(selectedEvent.created_at).toLocaleString() },
        { label: "Actor", value: selectedEvent.actor_email ?? "System" },
        { label: "Actor user ID", value: selectedEvent.actor_user_id ?? "-", mono: true },
        { label: "Actor role", value: selectedEvent.actor_role ?? "-" },
        { label: "Action", value: selectedEvent.action },
        { label: "Entity type", value: selectedEvent.entity_type },
        { label: "Entity ID", value: selectedEvent.entity_id ?? "-", mono: true },
        { label: "Signature algorithm", value: selectedEvent.signature_algorithm },
        { label: "Previous hash", value: selectedEvent.previous_hash ?? "Chain origin", mono: true },
        {
          label: "Event hash",
          value: selectedEvent.event_hash ?? "Unsigned legacy event",
          mono: true,
        },
      ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit"
        description="Mutation-grade actor trail for organization administration."
        actions={
          <>
            <Button variant="outline" size="sm" disabled={isExporting} onClick={downloadExport}>
              <Download data-icon="inline-start" />
              {isExporting ? "Exporting..." : "Export CSV"}
            </Button>
            <Button variant="outline" size="sm" disabled={isVerifying} onClick={verifyChain}>
              <ShieldCheck data-icon="inline-start" />
              {isVerifying ? "Verifying..." : "Verify chain"}
            </Button>
          </>
        }
      />

      {verification ? <VerificationAlert verification={verification} /> : null}

      <Card>
        <CardHeader className="border-b">
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Audit events</CardTitle>
            <Badge variant="outline">{events.length} loaded</Badge>
          </div>
          <FilterToolbar
            className="mt-3"
            chips={chips}
            onClearAll={chips.length > 0 ? clearFilters : undefined}
          >
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search actor, action, entity, selected metadata..."
                aria-label="Search audit events"
              />
            </div>
            <Input
              className="w-44"
              value={action}
              onChange={(event) => setAction(event.target.value)}
              placeholder="Exact action"
              aria-label="Filter by exact action"
            />
            <Input
              className="w-48 font-mono"
              value={actorUserId}
              onChange={(event) => setActorUserId(event.target.value)}
              placeholder="Actor user ID"
              aria-label="Filter by actor user ID"
            />
            <Select
              value={entityType}
              onValueChange={(value) => {
                setEntityType(value);
                if (value === ANY) setEntityId("");
              }}
            >
              <SelectTrigger className="w-48" aria-label="Filter by entity type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={ANY}>All entity types</SelectItem>
                  <SelectItem value="organization">Organization</SelectItem>
                  <SelectItem value="user">User</SelectItem>
                  <SelectItem value="invite">Invite</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="virtual_key">Virtual key</SelectItem>
                  <SelectItem value="provider">Provider</SelectItem>
                  <SelectItem value="policy_assignment">Policy assignment</SelectItem>
                  <SelectItem value="guardrail_policy">Guardrail policy</SelectItem>
                  <SelectItem value="guardrail_assignment">Guardrail assignment</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Input
              className="w-48 font-mono"
              value={entityId}
              disabled={entityType === ANY}
              onChange={(event) => setEntityId(event.target.value)}
              placeholder="Entity ID"
              aria-label="Filter by entity ID"
            />
            <Input
              type="date"
              className="w-40"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              aria-label="Audit start date"
            />
            <Input
              type="date"
              className="w-40"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              aria-label="Audit end date"
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
                loading={auditQuery.isPending}
                error={auditQuery.isError ? "Audit events could not be loaded." : undefined}
                onRetry={() => void auditQuery.refetch()}
                getRowKey={(event) => event.id}
                onRowClick={setSelectedEvent}
                empty={{
                  icon: Search,
                  title: "No audit events",
                  description: "Administrative mutations matching the filters will appear here.",
                }}
              />
              {auditQuery.hasNextPage ? (
                <div className="flex justify-center pt-4">
                  <Button
                    variant="outline"
                    disabled={auditQuery.isFetchingNextPage}
                    onClick={() => auditQuery.fetchNextPage()}
                  >
                    {auditQuery.isFetchingNextPage ? "Loading..." : "Load more"}
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
        title="Audit event details"
        description="Actor, resource, metadata, and chain verification fields for this event."
        rows={detailRows}
        json={selectedEvent?.metadata}
      />
    </div>
  );
}

function VerificationAlert({ verification }: { verification: AuditVerificationResponse }) {
  return (
    <Alert variant={verification.valid ? "default" : "destructive"}>
      {verification.valid ? <ShieldCheck /> : <AlertTriangle />}
      <AlertTitle>{verification.valid ? "Audit chain verified" : "Audit chain invalid"}</AlertTitle>
      <AlertDescription>
        {verification.valid
          ? `${verification.checked_events} events were verified.`
          : `${verification.reason ?? "Verification failed."}${
              verification.first_invalid_event_id
                ? ` First invalid event: ${verification.first_invalid_event_id}.`
                : ""
            }`}
      </AlertDescription>
    </Alert>
  );
}

function formatMetadata(metadata: Record<string, unknown>) {
  return Object.keys(metadata).length === 0 ? "-" : JSON.stringify(metadata);
}
