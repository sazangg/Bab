import { AlertTriangle, CheckCircle2, CircleSlash, Route, ShieldAlert } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  PolicySimulationDecision,
  PolicySimulationGuardrailResult,
  PolicySimulationLimitResult,
  PolicySimulationResponse,
  PolicySimulationRouteAttempt,
  PolicySimulationWarning,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge, type StatusVariant } from "@/shared/components/StatusBadge";

export function PolicySimulationResult({ result }: { result: PolicySimulationResponse | null }) {
  if (!result) {
    return (
      <Card>
        <CardContent className="py-8">
          <EmptyState
            icon={Route}
            title="No simulation yet"
            description="Run a policy simulation to inspect the effective route, limit checks, and guardrail decisions."
          />
        </CardContent>
      </Card>
    );
  }

  const routeAttempts = result.route_attempts ?? [];
  const decisions = result.decisions ?? [];
  const limitResults = result.limit_results ?? [];
  const guardrailResults = result.guardrail_results ?? [];
  const warnings = result.warnings ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Simulation result</CardTitle>
              <CardDescription>
                {result.subject.virtual_key_name ?? result.subject.virtual_key_id} requesting{" "}
                {result.requested_model}
              </CardDescription>
            </div>
            <StatusBadge variant={decisionVariant(result.final_decision)}>
              {formatValue(result.final_decision)}
            </StatusBadge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <SummaryItem label="Endpoint" value={formatValue(result.subject.gateway_endpoint)} />
          <SummaryItem label="Public model" value={result.public_model_name ?? "-"} />
          <SummaryItem label="Routing mode" value={formatValue(result.routing_mode ?? "-")} />
          <SummaryItem label="Denied stage" value={formatValue(result.denied_stage ?? "-")} />
          {result.denied_reason ? (
            <div className="rounded-md border bg-muted/30 p-3 md:col-span-2 xl:col-span-4">
              <div className="text-xs font-medium uppercase text-muted-foreground">Denied reason</div>
              <div className="mt-1 text-sm">{result.denied_reason}</div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {warnings.length > 0 ? <WarningsCard warnings={warnings} /> : null}
      <RouteAttemptsCard attempts={routeAttempts} />
      <DecisionsCard decisions={decisions} />
      <LimitResultsCard results={limitResults} />
      <GuardrailResultsCard results={guardrailResults} />
    </div>
  );
}

function WarningsCard({ warnings }: { warnings: PolicySimulationWarning[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="size-5 text-warning" />
          Warnings
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {warnings.map((warning, index) => (
          <div key={`${warning.code}-${index}`} className="rounded-md border bg-warning/5 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge variant="warning">{warning.code}</StatusBadge>
              {warning.draft_ref ? <StatusBadge variant="info">{warning.draft_ref}</StatusBadge> : null}
            </div>
            <div className="mt-2 text-sm">{warning.message}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RouteAttemptsCard({ attempts }: { attempts: PolicySimulationRouteAttempt[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Route attempts</CardTitle>
        <CardDescription>Access route candidates evaluated for the requested model.</CardDescription>
      </CardHeader>
      <CardContent>
        {attempts.length === 0 ? (
          <EmptyState icon={CircleSlash} title="No route attempts" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candidate</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Pool</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {attempts.map((attempt) => (
                <TableRow key={`${attempt.candidate_index}-${attempt.attempt_index ?? "x"}`}>
                  <TableCell>{attempt.candidate_index + 1}</TableCell>
                  <TableCell>
                    <StatusBadge variant={attempt.selected ? "success" : attempt.would_attempt ? "info" : "muted"}>
                      {attempt.selected ? "Selected" : attempt.would_attempt ? "Would try" : "Skipped"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>{attempt.provider_name ?? attempt.provider_id ?? "-"}</TableCell>
                  <TableCell>{attempt.credential_pool_name ?? attempt.credential_pool_id ?? "-"}</TableCell>
                  <TableCell>{attempt.provider_model ?? attempt.public_model_name ?? "-"}</TableCell>
                  <TableCell>{attempt.skipped_message ?? attempt.skipped_reason ?? "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function DecisionsCard({ decisions }: { decisions: PolicySimulationDecision[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy decisions</CardTitle>
        <CardDescription>Ordered decisions that contributed to the simulated outcome.</CardDescription>
      </CardHeader>
      <CardContent>
        {decisions.length === 0 ? (
          <EmptyState icon={CheckCircle2} title="No policy decisions" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stage</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Policy</TableHead>
                <TableHead>Rule</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {decisions.map((decision, index) => (
                <TableRow key={`${decision.stage}-${decision.policy_id ?? index}-${decision.rule_id ?? "none"}`}>
                  <TableCell>{formatValue(decision.stage)}</TableCell>
                  <TableCell>
                    <StatusBadge variant={decisionVariant(decision.outcome)}>
                      {formatValue(decision.outcome)}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>{decision.policy_name ?? decision.policy_id ?? "-"}</TableCell>
                  <TableCell>{decision.rule_name ?? decision.rule_id ?? "-"}</TableCell>
                  <TableCell>{decision.assignment_scope_label ?? decision.assignment_scope_type ?? "-"}</TableCell>
                  <TableCell>{decision.message ?? decision.reason_code ?? "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function LimitResultsCard({ results }: { results: PolicySimulationLimitResult[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Limit checks</CardTitle>
        <CardDescription>Quota and budget rules evaluated for the simulated request.</CardDescription>
      </CardHeader>
      <CardContent>
        {results.length === 0 ? (
          <EmptyState icon={CheckCircle2} title="No limit checks" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Limit</TableHead>
                <TableHead>Usage</TableHead>
                <TableHead>Decision</TableHead>
                <TableHead>Window</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.map((result, index) => (
                <TableRow key={`${result.rule_id ?? "rule"}-${index}`}>
                  <TableCell>{result.rule_name ?? result.rule_id ?? result.policy_name ?? "-"}</TableCell>
                  <TableCell>
                    {result.limit_value} {formatValue(result.counting_unit)}
                  </TableCell>
                  <TableCell>
                    {formatNumber(result.current_usage)} + {formatNumber(result.attempted_usage)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={result.would_deny ? "error" : "success"}>
                      {result.would_deny ? "Would deny" : "Allow"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>{result.window_descriptor ?? `${result.interval_count} ${result.interval_unit}`}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function GuardrailResultsCard({ results }: { results: PolicySimulationGuardrailResult[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Guardrail checks</CardTitle>
        <CardDescription>Prompt and response guardrail rules evaluated for this simulation.</CardDescription>
      </CardHeader>
      <CardContent>
        {results.length === 0 ? (
          <EmptyState icon={ShieldAlert} title="No guardrail checks" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Phase</TableHead>
                <TableHead>Rule</TableHead>
                <TableHead>Effect</TableHead>
                <TableHead>Decision</TableHead>
                <TableHead>Match</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.map((result, index) => (
                <TableRow key={`${result.rule_id ?? "guardrail"}-${index}`}>
                  <TableCell>{formatValue(result.phase)}</TableCell>
                  <TableCell>{result.rule_name ?? result.rule_id ?? result.policy_name ?? "-"}</TableCell>
                  <TableCell>{formatValue(result.effect)}</TableCell>
                  <TableCell>
                    <StatusBadge variant={decisionVariant(result.decision)}>
                      {formatValue(result.decision)}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>{result.matched_values?.join(", ") || result.reason_code || "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="text-xs font-medium uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value}</div>
    </div>
  );
}

function decisionVariant(value: string): StatusVariant {
  if (value === "allow" || value === "would_allow") return "success";
  if (value === "deny" || value === "would_deny" || value === "block") return "error";
  return "info";
}

function formatValue(value: string) {
  return value.replaceAll("_", " ");
}

function formatNumber(value: number | null | undefined) {
  return value ?? 0;
}
