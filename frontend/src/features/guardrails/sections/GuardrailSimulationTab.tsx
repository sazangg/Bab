import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PolicySimulationPanel } from "@/features/policies/components/PolicySimulationPanel";
import { PolicySimulationResult } from "@/features/policies/components/PolicySimulationResult";
import { useSimulateGuardrailsApiV1GuardrailsSimulatePost } from "@/shared/api/generated/guardrails/guardrails";
import type {
  GuardrailPolicyResponse,
  GuardrailSimulationResponse,
  PolicySimulationDraft,
  PolicySimulationResponse,
} from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { Field, SelectField } from "../components/GuardrailFormFields";
import {
  guardrailDecisionStatus,
  ruleEffectLabel,
  ruleTypeLabels,
  uuidPattern,
} from "../lib/guardrail-helpers";

export function GuardrailSimulationTab({
  policies,
  policySimulationDrafts = [],
  policySimulationResult,
  onPolicySimulationResult,
}: {
  policies: GuardrailPolicyResponse[];
  policySimulationDrafts?: PolicySimulationDraft[];
  policySimulationResult: PolicySimulationResponse | null;
  onPolicySimulationResult: (result: PolicySimulationResponse | null) => void;
}) {
  const [policyId, setPolicyId] = useState("");
  const [model, setModel] = useState("gpt-5-mini");
  const [providerModel, setProviderModel] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<GuardrailSimulationResponse | null>(null);

  const simulate = useSimulateGuardrailsApiV1GuardrailsSimulatePost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 200) setResult(response.data);
      },
      onError: () => toast.error("Simulation could not be run."),
    },
  });

  const runSimulation = () => {
    if (!policyId) {
      toast.error("Choose a policy to simulate.");
      return;
    }
    if (!model.trim()) {
      toast.error("Model is required.");
      return;
    }
    if (providerId.trim() && !uuidPattern.test(providerId.trim())) {
      toast.error("Provider ID must be a UUID.");
      return;
    }
    if (poolId.trim() && !uuidPattern.test(poolId.trim())) {
      toast.error("Pool ID must be a UUID.");
      return;
    }
    simulate.mutate({
      data: {
        policy_id: policyId,
        requested_model: model.trim(),
        provider_model: providerModel.trim() || null,
        provider_id: providerId.trim() || null,
        pool_id: poolId.trim() || null,
        prompt_text: prompt,
      },
    });
  };

  const decisionStatus = result ? guardrailDecisionStatus(result.decision) : null;

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <PolicySimulationPanel
          drafts={policySimulationDrafts}
          onResult={onPolicySimulationResult}
        />
        <PolicySimulationResult result={policySimulationResult} />
      </div>

      <Card>
      <CardHeader>
        <CardTitle>Simulation</CardTitle>
        <CardDescription>
          Test request-time policy context without recording an event or sending traffic.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <div className="grid gap-3">
            <div className="grid gap-3 md:grid-cols-2">
              <SelectField
                label="Policy"
                value={policyId}
                onValueChange={setPolicyId}
                options={policies.map((policy) => policy.id)}
                labels={Object.fromEntries(policies.map((policy) => [policy.id, policy.name]))}
                placeholder="Choose policy"
              />
              <Field label="Requested model">
                <Input value={model} onChange={(event) => setModel(event.target.value)} />
              </Field>
              <Field label="Provider model">
                <Input
                  value={providerModel}
                  onChange={(event) => setProviderModel(event.target.value)}
                  placeholder="Defaults to requested model"
                />
              </Field>
              <Field label="Provider ID">
                <Input
                  value={providerId}
                  onChange={(event) => setProviderId(event.target.value)}
                  placeholder="Optional UUID"
                />
              </Field>
              <Field label="Pool ID">
                <Input
                  value={poolId}
                  onChange={(event) => setPoolId(event.target.value)}
                  placeholder="Optional UUID"
                />
              </Field>
            </div>
            <Field label="Prompt">
              <Textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                className="min-h-28 resize-none"
                placeholder="Paste a prompt to test prompt and PII rules"
              />
            </Field>
            <p className="text-xs text-muted-foreground">
              Response-only rules are enforced on live responses; simulation evaluates the request
              context.
            </p>
            <div>
              <Button onClick={runSimulation} disabled={simulate.isPending}>
                <ShieldCheck data-icon="inline-start" />
                Run simulation
              </Button>
            </div>
          </div>
          <div className="rounded-md border bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Result</div>
              {decisionStatus ? (
                <StatusBadge variant={decisionStatus.variant}>{decisionStatus.label}</StatusBadge>
              ) : (
                <StatusBadge variant="muted">Not run</StatusBadge>
              )}
            </div>
            <div className="mt-3 grid gap-2 text-sm">
              {result ? (
                result.matches.length > 0 ? (
                  result.matches.map((match, index) => (
                    <div key={`${match.reason}-${index}`} className="rounded-md bg-background p-3">
                      <div className="font-medium">
                        {ruleTypeLabels[match.rule_type] ?? match.rule_type} ·{" "}
                        {ruleEffectLabel(match.effect)}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {match.reason} · priority {match.priority}
                      </div>
                      <div className="mt-2 font-mono text-xs">
                        {match.matched_values.length > 0
                          ? match.matched_values.join(", ")
                          : match.effect === "allow"
                            ? "Allowlist miss"
                            : "No direct value match"}
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">No rules would block this request.</p>
                )
              ) : (
                <p className="text-muted-foreground">
                  Simulation results will show matched rules and dry-run decisions here.
                </p>
              )}
            </div>
          </div>
        </div>
      </CardContent>
      </Card>
    </div>
  );
}
