import type { ReactNode } from "react";

import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useGetGatewayRequestTraceApiV1GatewayHistoryRequestsGatewayRequestIdGet } from "@/shared/api/generated/gateway-history/gateway-history";
import type {
  GatewayPolicyDecisionTrace,
  GatewayRequestTraceResponse,
  GatewayRouteAttemptTrace,
  GatewayTraceTimelineItem,
  GuardrailEventTrace,
  UsageRecordResponse,
} from "@/shared/api/generated/schemas";
import { getProblemDetail } from "@/shared/api/problem-detail";
import { formatCents } from "@/shared/lib/format-currency";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";

export function RequestTraceSheet({
  gatewayRequestId,
  open,
  onOpenChange,
}: {
  gatewayRequestId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const traceQuery = useGetGatewayRequestTraceApiV1GatewayHistoryRequestsGatewayRequestIdGet(
    gatewayRequestId ?? "",
    {
      query: {
        enabled: Boolean(gatewayRequestId),
      },
    },
  );
  const trace = traceQuery.data?.status === 200 ? traceQuery.data.data : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Request trace</SheetTitle>
          <SheetDescription>{shortId(gatewayRequestId)}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-6">
          {traceQuery.isPending && gatewayRequestId ? (
            <p className="text-sm text-muted-foreground">Loading trace...</p>
          ) : null}
          {traceQuery.error ? (
            <TraceErrorAlert error={traceQuery.error} onRetry={() => traceQuery.refetch()} />
          ) : null}
          {!traceQuery.isPending && !traceQuery.error && !trace ? (
            <p className="text-sm text-muted-foreground">No trace rows found.</p>
          ) : null}
          {trace ? <RequestTraceContent trace={trace} /> : null}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

function TraceErrorAlert({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>Trace unavailable</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span>{getProblemDetail(error, "Unable to load request trace.")}</span>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function RequestTraceContent({ trace }: { trace: GatewayRequestTraceResponse }) {
  return (
    <>
      <TraceSummaryBand trace={trace} />
      <TraceTimelineSection items={trace.timeline ?? []} />
      <TraceAttemptsSection attempts={trace.route_attempts ?? []} />
      <TracePolicySection decisions={trace.policy_decisions ?? []} />
      <TraceGuardrailSection events={trace.guardrail_events ?? []} />
      <TraceUsageSection records={trace.usage_records ?? []} />
    </>
  );
}

function TraceSummaryBand({ trace }: { trace: GatewayRequestTraceResponse }) {
  const request = trace.request;
  return (
    <section className="rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {request.public_model_name ?? request.requested_model}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {request.gateway_endpoint} / {shortId(request.request_id ?? request.id)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {request.final_http_status == null ? (
            <Badge variant="outline">Pending</Badge>
          ) : (
            <HttpStatusBadge status={request.final_http_status} />
          )}
          {request.fallback_attempted ? <Badge variant="secondary">Fallback attempted</Badge> : null}
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <TraceStat label="Attempts" value={request.attempt_count.toLocaleString()} />
        <TraceStat label="Started" value={new Date(request.started_at).toLocaleString()} />
        <TraceStat
          label="Completed"
          value={request.completed_at ? new Date(request.completed_at).toLocaleString() : "Pending"}
        />
      </div>
    </section>
  );
}

function TraceStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value}</div>
    </div>
  );
}

function TraceTimelineSection({ items }: { items: GatewayTraceTimelineItem[] }) {
  return (
    <TraceSection title="Timeline" count={items.length}>
      {items.length === 0 ? (
        <TraceEmpty />
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div key={`${item.timestamp}-${item.kind}-${index}`} className="rounded-md border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{timelineTitle(item)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {new Date(item.timestamp).toLocaleString()}
                    {item.stage ? ` / ${item.stage}` : ""}
                  </div>
                </div>
                <Badge variant={timelineBadgeVariant(item)}>{timelineBadgeLabel(item)}</Badge>
              </div>
              {item.summary ? (
                <div className="mt-2 text-xs text-muted-foreground">{item.summary}</div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </TraceSection>
  );
}

function TraceAttemptsSection({ attempts }: { attempts: GatewayRouteAttemptTrace[] }) {
  return (
    <TraceSection title="Route attempts" count={attempts.length}>
      {attempts.length === 0 ? (
        <TraceEmpty />
      ) : (
        <div className="space-y-2">
          {attempts.map((attempt) => (
            <div key={attempt.id} className="rounded-md border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    #{attempt.attempt_index + 1} {attempt.provider_name ?? "Provider"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {attempt.provider_model ?? attempt.public_model_name ?? "-"}
                  </div>
                </div>
                <Badge variant={routeAttemptBadgeVariant(attempt)}>
                  {routeAttemptLabel(attempt)}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                <span>{attempt.http_status ? `${attempt.http_status}` : "No status"}</span>
                <span>{attempt.latency_ms != null ? `${attempt.latency_ms}ms` : "No latency"}</span>
                <span>{formatCents(attempt.cost_cents ?? 0)}</span>
              </div>
              {attempt.error_code || attempt.failure_reason ? (
                <div className="mt-2 text-xs text-destructive">
                  {attempt.error_code ?? attempt.failure_reason}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </TraceSection>
  );
}

function TracePolicySection({ decisions }: { decisions: GatewayPolicyDecisionTrace[] }) {
  return (
    <TraceSection title="Policy decisions" count={decisions.length}>
      {decisions.length === 0 ? (
        <TraceEmpty />
      ) : (
        <div className="space-y-2">
          {decisions.map((decision) => (
            <div key={decision.id} className="rounded-md border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{policyDecisionTitle(decision)}</div>
                <Badge variant={policyDecisionBadgeVariant(decision.outcome)}>
                  {policyDecisionLabel(decision.outcome)}
                </Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {decision.stage} / {decision.effective_action ?? "recorded"}
              </div>
              {decision.reason_code || decision.message ? (
                <div className="mt-2 text-xs text-muted-foreground">
                  {decision.reason_code ?? decision.message}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </TraceSection>
  );
}

function timelineTitle(item: GatewayTraceTimelineItem) {
  if (item.title) return item.title;
  if (item.kind === "request") return "Request";
  if (item.kind === "route_attempt") return "Route attempt";
  if (item.kind === "policy_decision") return "Policy decision";
  if (item.kind === "guardrail_event") return "Guardrail event";
  if (item.kind === "usage_record") return "Usage recorded";
  return "Trace event";
}

function timelineBadgeLabel(item: GatewayTraceTimelineItem) {
  if (item.kind === "usage_record") return "Limit reserved";
  if (item.status === "denied" || item.status === "blocked") return "Denied";
  if (item.status === "would_deny" || item.status === "would_block") return "Would deny";
  if (item.status === "failed") return "Provider failed";
  if (item.status === "succeeded" || item.status === "allowed") return "Allowed";
  return item.status ?? item.kind.replaceAll("_", " ");
}

function timelineBadgeVariant(item: GatewayTraceTimelineItem) {
  if (item.severity === "error" || item.status === "denied" || item.status === "blocked") {
    return "destructive";
  }
  if (item.severity === "warning" || item.status === "failed") return "secondary";
  return "outline";
}

function routeAttemptLabel(attempt: GatewayRouteAttemptTrace) {
  if (attempt.fallback_from_attempt_id) return "Fallback attempted";
  if (attempt.status === "succeeded") return "Allowed";
  if (attempt.status === "failed") return "Provider failed";
  if (attempt.status === "blocked") return "Denied";
  if (attempt.skipped_reason) return "Skipped";
  return attempt.status.replaceAll("_", " ");
}

function routeAttemptBadgeVariant(attempt: GatewayRouteAttemptTrace) {
  if (attempt.status === "succeeded") return "default";
  if (attempt.status === "failed" || attempt.status === "blocked") return "destructive";
  return "secondary";
}

function policyDecisionTitle(decision: GatewayPolicyDecisionTrace) {
  if (decision.decision_type === "limit") return "Limit policy";
  if (decision.decision_type === "routing") return "Routing policy";
  if (decision.decision_type === "access") return "Access policy";
  return decision.decision_type.replaceAll("_", " ");
}

function policyDecisionLabel(outcome: string) {
  if (outcome === "allowed" || outcome === "would_allow") return "Allowed";
  if (outcome === "denied") return "Denied";
  if (outcome === "would_deny") return "Would deny";
  return outcome.replaceAll("_", " ");
}

function policyDecisionBadgeVariant(outcome: string) {
  if (outcome === "allowed" || outcome === "would_allow") return "default";
  if (outcome === "denied" || outcome === "would_deny") return "destructive";
  return "secondary";
}

function guardrailDecisionLabel(decision: string) {
  if (decision === "allowed") return "Allowed";
  if (decision === "blocked") return "Denied";
  if (decision === "would_block") return "Would deny";
  return decision.replaceAll("_", " ");
}

function guardrailDecisionBadgeVariant(decision: string) {
  if (decision === "blocked" || decision === "would_block") return "destructive";
  return "secondary";
}

function TraceGuardrailSection({ events }: { events: GuardrailEventTrace[] }) {
  return (
    <TraceSection title="Guardrail events" count={events.length}>
      {events.length === 0 ? (
        <TraceEmpty />
      ) : (
        <div className="space-y-2">
          {events.map((event) => (
            <div key={event.id} className="rounded-md border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{event.reason}</div>
                <Badge variant={guardrailDecisionBadgeVariant(event.decision)}>
                  {guardrailDecisionLabel(event.decision)}
                </Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {event.phase} / {event.provider_model ?? event.requested_model ?? "-"}
              </div>
            </div>
          ))}
        </div>
      )}
    </TraceSection>
  );
}

function TraceUsageSection({ records }: { records: UsageRecordResponse[] }) {
  return (
    <TraceSection title="Usage records" count={records.length}>
      {records.length === 0 ? (
        <TraceEmpty />
      ) : (
        <div className="space-y-2">
          {records.map((record) => (
            <div key={record.id} className="rounded-md border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{record.provider_model}</div>
                <HttpStatusBadge status={record.http_status} />
              </div>
              <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                <span>{(record.total_tokens ?? 0).toLocaleString()} tokens</span>
                <span>
                  {formatCents(record.confirmed_spend_cents + record.estimated_spend_cents)}
                </span>
                <span>{record.latency_ms}ms</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </TraceSection>
  );
}

function TraceSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">{title}</h3>
        <Badge variant="outline">{count}</Badge>
      </div>
      {children}
    </section>
  );
}

function TraceEmpty() {
  return <p className="text-sm text-muted-foreground">None recorded.</p>;
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}
