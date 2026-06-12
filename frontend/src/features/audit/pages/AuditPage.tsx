import { useInfiniteQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardList, Download, Search, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { httpClient } from "@/shared/api/http-client";
import type { AuditEventResponse, AuditVerificationResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

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
      const response = await httpClient.get<AuditEventResponse[]>("/api/v1/auth/audit", {
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
      const response = await httpClient.get<Blob>("/api/v1/auth/audit/export", {
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
      const response = await httpClient.get<AuditVerificationResponse>("/api/v1/auth/audit/verify");
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
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Audit events</CardTitle>
              <Badge variant="outline">{events.length} loaded</Badge>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <div className="relative sm:col-span-2">
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
                value={action}
                onChange={(event) => setAction(event.target.value)}
                placeholder="Exact action"
                aria-label="Filter by exact action"
              />
              <Input
                className="font-mono"
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
                <SelectTrigger className="w-full" aria-label="Filter by entity type">
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
                className="font-mono"
                value={entityId}
                disabled={entityType === ANY}
                onChange={(event) => setEntityId(event.target.value)}
                placeholder="Entity ID"
                aria-label="Filter by entity ID"
              />
              <Input
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
                aria-label="Audit start date"
              />
              <Input
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
                aria-label="Audit end date"
              />
              <div className="flex justify-end sm:col-span-2 lg:col-span-4">
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {dateRange.error ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>Invalid date range</AlertTitle>
              <AlertDescription>{dateRange.error}</AlertDescription>
            </Alert>
          ) : auditQuery.isPending ? (
            <AuditSkeleton />
          ) : auditQuery.isError ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>Audit events could not be loaded</AlertTitle>
              <AlertDescription className="flex items-center justify-between gap-3">
                Check the filters and connection, then try again.
                <Button variant="outline" size="sm" onClick={() => auditQuery.refetch()}>
                  Retry
                </Button>
              </AlertDescription>
            </Alert>
          ) : events.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No audit events"
              description="Administrative mutations matching the filters will appear here."
            />
          ) : (
            <div className="overflow-x-auto">
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
                  {events.map((event) => (
                    <TableRow
                      key={event.id}
                      className="cursor-pointer"
                      tabIndex={0}
                      onClick={() => setSelectedEvent(event)}
                      onKeyDown={(keyEvent) => {
                        if (keyEvent.key === "Enter" || keyEvent.key === " ") {
                          keyEvent.preventDefault();
                          setSelectedEvent(event);
                        }
                      }}
                    >
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
            </div>
          )}
          {auditQuery.hasNextPage ? (
            <div className="flex justify-center border-t pt-4">
              <Button
                variant="outline"
                disabled={auditQuery.isFetchingNextPage}
                onClick={() => auditQuery.fetchNextPage()}
              >
                {auditQuery.isFetchingNextPage ? "Loading..." : "Load more"}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <AuditDetailSheet
        event={selectedEvent}
        onOpenChange={(open) => !open && setSelectedEvent(null)}
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

function AuditDetailSheet({
  event,
  onOpenChange,
}: {
  event: AuditEventResponse | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={Boolean(event)} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Audit event details</SheetTitle>
          <SheetDescription>
            Actor, resource, metadata, and chain verification fields for this event.
          </SheetDescription>
        </SheetHeader>
        {event ? (
          <SheetBody className="flex flex-col gap-5">
            <Detail label="Event ID" value={event.id} mono />
            <Detail label="Created" value={new Date(event.created_at).toLocaleString()} />
            <Detail label="Actor" value={event.actor_email ?? "System"} />
            <Detail label="Actor user ID" value={event.actor_user_id ?? "-"} mono />
            <Detail label="Actor role" value={event.actor_role ?? "-"} />
            <Detail label="Action" value={event.action} />
            <Detail label="Entity type" value={event.entity_type} />
            <Detail label="Entity ID" value={event.entity_id ?? "-"} mono />
            <Detail label="Signature algorithm" value={event.signature_algorithm} />
            <Detail label="Previous hash" value={event.previous_hash ?? "Chain origin"} mono />
            <Detail label="Event hash" value={event.event_hash ?? "Unsigned legacy event"} mono />
            <div className="flex flex-col gap-1">
              <div className="text-xs font-medium text-muted-foreground">Metadata</div>
              <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(event.metadata, null, 2)}
              </pre>
            </div>
          </SheetBody>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={mono ? "break-all font-mono text-xs" : "text-sm"}>{value}</div>
    </div>
  );
}

function formatMetadata(metadata: Record<string, unknown>) {
  return Object.keys(metadata).length === 0 ? "-" : JSON.stringify(metadata);
}

function buildDateRange(
  startDate: string,
  endDate: string,
): { startAt?: string; endAt?: string; error?: string } {
  const startAt = toDateBoundary(startDate, "00:00:00");
  const endAt = toDateBoundary(endDate, "23:59:59");
  if (startDate && !startAt) return { error: "The start date is invalid." };
  if (endDate && !endAt) return { error: "The end date is invalid." };
  if (startAt && endAt && startAt > endAt) {
    return { error: "The start date must be before the end date." };
  }
  return { startAt, endAt };
}

function toDateBoundary(value: string, time: string) {
  if (!value) return undefined;
  const date = new Date(`${value}T${time}`);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

function useDebouncedValue(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timeout);
  }, [delay, value]);
  return debounced;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function AuditSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-label="Loading audit events">
      {Array.from({ length: 5 }, (_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  );
}
