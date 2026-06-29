import { Eye, ShieldX } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useListEventsApiV1GuardrailsEventsGet } from "@/shared/api/generated/guardrails/guardrails";
import type {
  GuardrailEventResponse,
  GuardrailPolicyResponse,
} from "@/shared/api/generated/schemas";
import { FilterToolbar, type FilterChip } from "@/shared/components/FilterToolbar";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { RequestTraceSheet } from "@/features/usage/components/RequestTraceSheet";

import {
  guardrailDecisionStatus,
  labelEventScope,
  shortId,
  uuidPattern,
  type EventScopeType,
  type ScopeOptions,
} from "../lib/guardrail-helpers";

export function GuardrailEventsTab({
  policies,
  policyLabels,
  scopeOptions,
  scopeLabels,
}: {
  policies: GuardrailPolicyResponse[];
  policyLabels: Record<string, string>;
  scopeOptions: ScopeOptions;
  scopeLabels: Record<string, string>;
}) {
  const [decision, setDecision] = useState("all");
  const [policyId, setPolicyId] = useState("all");
  const [phase, setPhase] = useState("all");
  const [scopeType, setScopeType] = useState<EventScopeType>("all");
  const [scopeId, setScopeId] = useState("all");
  const [model, setModel] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null);

  const ruleIdFilter = ruleId.trim();
  const providerIdFilter = providerId.trim();
  const poolIdFilter = poolId.trim();

  const eventsQuery = useListEventsApiV1GuardrailsEventsGet({
    decision: decision === "all" ? undefined : decision,
    policy_id: policyId === "all" ? undefined : policyId,
    phase: phase === "all" ? undefined : phase,
    rule_id: uuidPattern.test(ruleIdFilter) ? ruleIdFilter : undefined,
    team_id: scopeType === "team" && scopeId !== "all" ? scopeId : undefined,
    project_id: scopeType === "project" && scopeId !== "all" ? scopeId : undefined,
    virtual_key_id: scopeType === "virtual_key" && scopeId !== "all" ? scopeId : undefined,
    provider_id: uuidPattern.test(providerIdFilter) ? providerIdFilter : undefined,
    pool_id: uuidPattern.test(poolIdFilter) ? poolIdFilter : undefined,
    model: model.trim() || undefined,
    limit: 50,
  });
  const events = eventsQuery.data?.status === 200 ? eventsQuery.data.data.items : [];
  const eventScopeOptions = scopeType === "all" ? [] : scopeOptions[scopeType];

  const clearScope = () => {
    setScopeType("all");
    setScopeId("all");
  };
  const clearAll = () => {
    setDecision("all");
    setPolicyId("all");
    setPhase("all");
    clearScope();
    setModel("");
    setRuleId("");
    setProviderId("");
    setPoolId("");
  };

  const chips: FilterChip[] = [];
  if (decision !== "all") {
    chips.push({
      key: "decision",
      label: `Decision: ${guardrailDecisionStatus(decision).label}`,
      onRemove: () => setDecision("all"),
    });
  }
  if (phase !== "all") {
    chips.push({ key: "phase", label: `Phase: ${phase}`, onRemove: () => setPhase("all") });
  }
  if (policyId !== "all") {
    chips.push({
      key: "policy",
      label: `Policy: ${policyLabels[policyId] ?? policyId}`,
      onRemove: () => setPolicyId("all"),
    });
  }
  if (scopeType !== "all") {
    const scopeLabel = scopeType.replace("_", " ");
    chips.push({
      key: "scope",
      label:
        scopeId !== "all"
          ? `Scope: ${scopeLabels[scopeId] ?? scopeId}`
          : `Scope: all ${scopeLabel}s`,
      onRemove: clearScope,
    });
  }
  if (model.trim()) {
    chips.push({ key: "model", label: `Model: ${model.trim()}`, onRemove: () => setModel("") });
  }
  if (ruleId.trim()) {
    chips.push({
      key: "rule",
      label: `Rule: ${shortId(ruleId.trim())}`,
      onRemove: () => setRuleId(""),
    });
  }
  if (providerId.trim()) {
    chips.push({
      key: "provider",
      label: `Provider: ${shortId(providerId.trim())}`,
      onRemove: () => setProviderId(""),
    });
  }
  if (poolId.trim()) {
    chips.push({
      key: "pool",
      label: `Pool: ${shortId(poolId.trim())}`,
      onRemove: () => setPoolId(""),
    });
  }

  const columns: DataTableColumn<GuardrailEventResponse>[] = [
    {
      key: "decision",
      header: "Decision",
      cell: (event) => {
        const status = guardrailDecisionStatus(event.decision);
        return <StatusBadge variant={status.variant}>{status.label}</StatusBadge>;
      },
    },
    {
      key: "policy",
      header: "Policy",
      cell: (event) => (
        <>
          <div>{event.policy_id ? (policyLabels[event.policy_id] ?? "Policy") : "-"}</div>
          <div className="text-xs text-muted-foreground">
            {event.phase} · {event.reason}
          </div>
        </>
      ),
    },
    {
      key: "model",
      header: "Model",
      className: "font-mono text-xs",
      cell: (event) => event.requested_model ?? "-",
    },
    {
      key: "request",
      header: "Request",
      cell: (event) => (
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">
            {shortId(event.request_id)}
          </span>
          {event.gateway_request_id ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Open request trace"
              onClick={() => setTraceRequestId(event.gateway_request_id)}
            >
              <Eye />
            </Button>
          ) : null}
        </div>
      ),
    },
    {
      key: "scope",
      header: "Scope",
      className: "text-xs text-muted-foreground",
      cell: (event) => labelEventScope(event, scopeLabels),
    },
  ];

  return (
    <>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Recent events</CardTitle>
            <CardDescription>Append-only guardrail decisions from proxy traffic.</CardDescription>
          </div>
          <div className="mt-4">
            <FilterToolbar chips={chips} onClearAll={chips.length > 0 ? clearAll : undefined}>
              <Select value={decision} onValueChange={setDecision}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All decisions</SelectItem>
                  <SelectItem value="allowed">Allowed</SelectItem>
                  <SelectItem value="dry_run">Dry run</SelectItem>
                  <SelectItem value="blocked">Blocked</SelectItem>
                </SelectContent>
              </Select>
              <Select value={phase} onValueChange={setPhase}>
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All phases</SelectItem>
                  <SelectItem value="request">Request</SelectItem>
                  <SelectItem value="response">Response</SelectItem>
                </SelectContent>
              </Select>
              <Select value={policyId} onValueChange={setPolicyId}>
                <SelectTrigger className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All policies</SelectItem>
                  {policies.map((policy) => (
                    <SelectItem key={policy.id} value={policy.id}>
                      {policy.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={scopeType}
                onValueChange={(value) => {
                  setScopeType(value as EventScopeType);
                  setScopeId("all");
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All scopes</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="virtual_key">Virtual key</SelectItem>
                </SelectContent>
              </Select>
              {scopeType !== "all" ? (
                <Select value={scopeId} onValueChange={setScopeId}>
                  <SelectTrigger className="w-56">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All {scopeType.replace("_", " ")}s</SelectItem>
                    {eventScopeOptions.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              <Input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="Filter model"
                className="w-44"
              />
              <Input
                value={ruleId}
                onChange={(event) => setRuleId(event.target.value)}
                placeholder="Filter rule ID"
                className="w-44"
              />
              <Input
                value={providerId}
                onChange={(event) => setProviderId(event.target.value)}
                placeholder="Filter provider ID"
                className="w-44"
              />
              <Input
                value={poolId}
                onChange={(event) => setPoolId(event.target.value)}
                placeholder="Filter pool ID"
                className="w-44"
              />
            </FilterToolbar>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={events}
            loading={eventsQuery.isPending}
            error={eventsQuery.isError ? "Could not load guardrail events." : undefined}
            onRetry={() => void eventsQuery.refetch()}
            getRowKey={(event) => event.id}
            empty={{
              icon: ShieldX,
              title: "No guardrail events",
              description: "Events appear when proxied requests pass or fail assigned policies.",
            }}
          />
        </CardContent>
      </Card>
      <RequestTraceSheet
        gatewayRequestId={traceRequestId}
        open={Boolean(traceRequestId)}
        onOpenChange={(open) => {
          if (!open) setTraceRequestId(null);
        }}
      />
    </>
  );
}
