import { AlertTriangle, History } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useListGatewayRequestsApiV1GatewayHistoryRequestsGet } from "@/shared/api/generated/gateway-history/gateway-history";
import type {
  GatewayRequestTraceListItem,
  ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams,
} from "@/shared/api/generated/schemas";
import { getProblemDetail } from "@/shared/api/problem-detail";
import { PageHeader } from "@/shared/components/PageHeader";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";
import { RequestTraceSheet } from "@/features/gateway-history/components/RequestTraceSheet";

const PAGE_SIZE = 25;

type HistoryWindow = NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["window"]>;
type HistoryStatus = NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["status"]>;
type HistoryFallback =
  NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["fallback"]>;

export function GatewayHistoryPage() {
  const [window, setWindow] = useState<HistoryWindow>("24h");
  const [status, setStatus] = useState<HistoryStatus | "all">("all");
  const [fallback, setFallback] = useState<HistoryFallback | "all">("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null);
  const trimmedSearch = search.trim();
  const params = useMemo(
    () => buildGatewayHistoryParams({ window, status, fallback, search: trimmedSearch, page }),
    [fallback, page, status, trimmedSearch, window],
  );
  const requestsQuery = useListGatewayRequestsApiV1GatewayHistoryRequestsGet(params);
  const pageData =
    requestsQuery.data?.status === 200
      ? requestsQuery.data.data
      : { items: [], has_more: false, limit: PAGE_SIZE, offset: page * PAGE_SIZE };
  const start = pageData.items.length > 0 ? page * PAGE_SIZE + 1 : 0;
  const end = page * PAGE_SIZE + pageData.items.length;
  const hasActiveFilters =
    trimmedSearch.length > 0 || status !== "all" || fallback !== "all" || window !== "24h";
  const clearFilters = () => {
    setSearch("");
    setStatus("all");
    setFallback("all");
    setWindow("24h");
    setPage(0);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Gateway history"
        description="Search recent gateway requests and open request traces."
        actions={
          <>
            <Select
              value={window}
              onValueChange={(value) => {
                setWindow(value as HistoryWindow);
                setPage(0);
              }}
            >
              <SelectTrigger className="w-36" aria-label="History window">
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
            <Select
              value={fallback}
              onValueChange={(value) => {
                setFallback(value as HistoryFallback | "all");
                setPage(0);
              }}
            >
              <SelectTrigger className="w-40" aria-label="Fallback status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All fallback states</SelectItem>
                <SelectItem value="attempted">Fallback attempted</SelectItem>
                <SelectItem value="not_attempted">No fallback</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={status}
              onValueChange={(value) => {
                setStatus(value as HistoryStatus | "all");
                setPage(0);
              }}
            >
              <SelectTrigger className="w-36" aria-label="Request status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="succeeded">Succeeded</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
                <SelectItem value="denied">Denied</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
              </SelectContent>
            </Select>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Search gateway requests"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(0);
          }}
          placeholder="Search request id, model, provider, key..."
          className="max-w-md"
        />
        {hasActiveFilters ? (
          <Button type="button" variant="outline" onClick={clearFilters}>
            Clear filters
          </Button>
        ) : null}
      </div>

      {requestsQuery.isError ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>Gateway history failed</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{getProblemDetail(requestsQuery.error, "Unable to load gateway history.")}</span>
            <Button variant="outline" size="sm" onClick={() => requestsQuery.refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <DataTable
        data={pageData.items}
        loading={requestsQuery.isPending}
        error={requestsQuery.isError ? "Unable to load gateway history." : false}
        onRetry={() => requestsQuery.refetch()}
        getRowKey={(request) => request.id}
        onRowClick={(request) => setTraceRequestId(request.id)}
        empty={{
          icon: History,
          title: hasActiveFilters ? "No gateway requests match" : "No gateway requests yet",
          description: hasActiveFilters
            ? "No requests match the current history filters."
            : "Gateway requests will appear here after proxy traffic is recorded.",
          action: hasActiveFilters ? (
            <Button type="button" variant="outline" onClick={clearFilters}>
              Clear filters
            </Button>
          ) : undefined,
        }}
        columns={[
          {
            key: "request",
            header: "Request",
            cell: (request) => (
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">
                  {shortId(request.request_id ?? request.id)}
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">
                  {request.gateway_endpoint} / {request.public_model_name ?? request.requested_model}
                </div>
              </div>
            ),
          },
          {
            key: "scope",
            header: "Scope",
            cell: (request) => request.project_name ?? request.team_name ?? "Authorized scope",
          },
          {
            key: "provider",
            header: "Provider",
            cell: (request) => request.final_provider_name ?? formatInvolvedProviders(request),
          },
          {
            key: "status",
            header: "Status",
            cell: (request) =>
              request.final_http_status == null ? (
                <span className="text-sm text-muted-foreground">{formatOutcome(request)}</span>
              ) : (
                <HttpStatusBadge status={request.final_http_status} />
              ),
          },
          {
            key: "started",
            header: "Started",
            cell: (request) => new Date(request.started_at).toLocaleString(),
          },
          {
            key: "duration",
            header: "Duration",
            align: "right",
            cell: (request) => (request.duration_ms == null ? "-" : `${request.duration_ms}ms`),
          },
        ]}
        footer={
          pageData.items.length > 0 ? (
            <>
              <span>
                Showing {start.toLocaleString()}-{end.toLocaleString()}
                {pageData.has_more ? " of more requests" : ""}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!pageData.has_more}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </>
          ) : undefined
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

export function buildGatewayHistoryParams({
  window,
  status,
  fallback,
  search,
  page,
}: {
  window: HistoryWindow;
  status: HistoryStatus | "all";
  fallback: HistoryFallback | "all";
  search: string;
  page: number;
}): ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams {
  return {
    window,
    status: status === "all" ? undefined : status,
    fallback: fallback === "all" ? undefined : fallback,
    search: search || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
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
