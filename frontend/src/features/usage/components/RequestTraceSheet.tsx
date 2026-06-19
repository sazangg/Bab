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
import { useGetGatewayRequestTraceApiV1UsageRequestsGatewayRequestIdGet } from "@/shared/api/generated/usage/usage";
import type {
  GatewayPolicyDecisionTrace,
  GatewayRequestTraceResponse,
  GatewayRouteAttemptTrace,
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
  const traceQuery = useGetGatewayRequestTraceApiV1UsageRequestsGatewayRequestIdGet(
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
  const request = trace.request;
  return (
    <>
      <section className="grid gap-3 sm:grid-cols-2">
        <TraceStat label="Model" value={request.public_model_name ?? request.requested_model} />
        <TraceStat label="Endpoint" value={request.gateway_endpoint} />
        <TraceStat
          label="Status"
          value={request.final_http_status ? String(request.final_http_status) : "Pending"}
        />
        <TraceStat label="Attempts" value={request.attempt_count.toLocaleString()} />
        <TraceStat label="Fallback" value={request.fallback_attempted ? "Attempted" : "No"} />
        <TraceStat label="Started" value={new Date(request.started_at).toLocaleString()} />
      </section>
      <TraceAttemptsSection attempts={trace.route_attempts ?? []} />
      <TracePolicySection decisions={trace.policy_decisions ?? []} />
      <TraceGuardrailSection events={trace.guardrail_events ?? []} />
      <TraceUsageSection records={trace.usage_records ?? []} />
    </>
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
                <Badge variant={attempt.status === "success" ? "default" : "secondary"}>
                  {attempt.status}
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
                <div className="font-medium">{decision.decision_type}</div>
                <Badge variant={policyDecisionBadgeVariant(decision.outcome)}>
                  {decision.outcome}
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

function policyDecisionBadgeVariant(outcome: string) {
  if (outcome === "allowed" || outcome === "would_allow") return "default";
  if (outcome === "denied") return "destructive";
  return "secondary";
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
                  {event.decision}
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
