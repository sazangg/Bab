import { Play, RotateCcw } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSimulatePoliciesApiV1PoliciesSimulationsPost } from "@/shared/api/generated/policies/policies";
import type {
  PolicySimulationDraft,
  PolicySimulationRequest,
  PolicySimulationRequestGatewayEndpoint,
  PolicySimulationResponse,
} from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

type SimulationFormState = {
  virtualKeyId: string;
  requestedModel: string;
  gatewayEndpoint: PolicySimulationRequestGatewayEndpoint;
  providerId: string;
  streaming: boolean;
  includeLimits: boolean;
  includeGuardrails: boolean;
  evaluateAllRouteCandidates: boolean;
  estimatedInputTokens: string;
  requestedOutputTokens: string;
  promptText: string;
  responseText: string;
};

const defaultState: SimulationFormState = {
  virtualKeyId: "",
  requestedModel: "",
  gatewayEndpoint: "chat_completions",
  providerId: "",
  streaming: false,
  includeLimits: true,
  includeGuardrails: true,
  evaluateAllRouteCandidates: true,
  estimatedInputTokens: "",
  requestedOutputTokens: "",
  promptText: "",
  responseText: "",
};

const endpointOptions: { value: PolicySimulationRequestGatewayEndpoint; label: string }[] = [
  { value: "chat_completions", label: "Chat completions" },
  { value: "responses", label: "Responses" },
  { value: "completions", label: "Completions" },
  { value: "anthropic_messages", label: "Anthropic messages" },
];

export function PolicySimulationPanel({
  drafts = [],
  onResult,
}: {
  drafts?: PolicySimulationDraft[];
  onResult?: (result: PolicySimulationResponse | null) => void;
}) {
  const [form, setForm] = useState<SimulationFormState>(defaultState);
  const [result, setResult] = useState<PolicySimulationResponse | null>(null);
  const simulation = useSimulatePoliciesApiV1PoliciesSimulationsPost({
    mutation: {
      onSuccess: (response) => {
        if (response.status !== 200) {
          toast.error("Policy simulation could not be completed.");
          return;
        }
        setResult(response.data);
        onResult?.(response.data);
      },
      onError: () => toast.error("Policy simulation could not be completed."),
    },
  });

  const canSubmit = form.virtualKeyId.trim().length > 0 && form.requestedModel.trim().length > 0;

  const reset = () => {
    setForm(defaultState);
    setResult(null);
    onResult?.(null);
  };

  const submit = () => {
    if (!canSubmit) return;
    simulation.mutate({
      data: buildSimulationRequest(form, drafts),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy simulation</CardTitle>
        <CardDescription>
          Test routing, limits, and guardrails for a virtual key without recording usage.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Virtual key ID" htmlFor="policy-simulation-key">
            <Input
              id="policy-simulation-key"
              value={form.virtualKeyId}
              onChange={(event) => setFormField(setForm, "virtualKeyId", event.target.value)}
              placeholder="vk_..."
            />
          </Field>
          <Field label="Requested model" htmlFor="policy-simulation-model">
            <Input
              id="policy-simulation-model"
              value={form.requestedModel}
              onChange={(event) => setFormField(setForm, "requestedModel", event.target.value)}
              placeholder="gpt-4.1-mini"
            />
          </Field>
          <Field label="Gateway endpoint" htmlFor="policy-simulation-endpoint">
            <Select
              value={form.gatewayEndpoint}
              onValueChange={(value) =>
                setFormField(
                  setForm,
                  "gatewayEndpoint",
                  value as PolicySimulationRequestGatewayEndpoint,
                )
              }
            >
              <SelectTrigger id="policy-simulation-endpoint">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {endpointOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Pinned provider ID" htmlFor="policy-simulation-provider">
            <Input
              id="policy-simulation-provider"
              value={form.providerId}
              onChange={(event) => setFormField(setForm, "providerId", event.target.value)}
              placeholder="Optional"
            />
          </Field>
          <Field label="Estimated input tokens" htmlFor="policy-simulation-input-tokens">
            <Input
              id="policy-simulation-input-tokens"
              inputMode="numeric"
              min={0}
              type="number"
              value={form.estimatedInputTokens}
              onChange={(event) =>
                setFormField(setForm, "estimatedInputTokens", event.target.value)
              }
              placeholder="0"
            />
          </Field>
          <Field label="Requested output tokens" htmlFor="policy-simulation-output-tokens">
            <Input
              id="policy-simulation-output-tokens"
              inputMode="numeric"
              min={0}
              type="number"
              value={form.requestedOutputTokens}
              onChange={(event) =>
                setFormField(setForm, "requestedOutputTokens", event.target.value)
              }
              placeholder="Optional"
            />
          </Field>
        </div>

        <div className="grid gap-3 rounded-md border p-4 sm:grid-cols-2 lg:grid-cols-4">
          <ToggleField
            label="Streaming"
            checked={form.streaming}
            onCheckedChange={(checked) => setFormField(setForm, "streaming", checked)}
          />
          <ToggleField
            label="Include limits"
            checked={form.includeLimits}
            onCheckedChange={(checked) => setFormField(setForm, "includeLimits", checked)}
          />
          <ToggleField
            label="Include guardrails"
            checked={form.includeGuardrails}
            onCheckedChange={(checked) => setFormField(setForm, "includeGuardrails", checked)}
          />
          <ToggleField
            label="All route candidates"
            checked={form.evaluateAllRouteCandidates}
            onCheckedChange={(checked) =>
              setFormField(setForm, "evaluateAllRouteCandidates", checked)
            }
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Prompt text" htmlFor="policy-simulation-prompt">
            <Textarea
              id="policy-simulation-prompt"
              rows={5}
              value={form.promptText}
              onChange={(event) => setFormField(setForm, "promptText", event.target.value)}
              placeholder="Optional guardrail prompt input"
            />
          </Field>
          <Field label="Response text" htmlFor="policy-simulation-response">
            <Textarea
              id="policy-simulation-response"
              rows={5}
              value={form.responseText}
              onChange={(event) => setFormField(setForm, "responseText", event.target.value)}
              placeholder="Optional guardrail response input"
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {drafts.length > 0 ? (
              <StatusBadge variant="info">{drafts.length} draft change(s)</StatusBadge>
            ) : (
              <StatusBadge variant="muted">Active policies</StatusBadge>
            )}
            {result ? (
              <span>
                Last result: <span className="font-medium text-foreground">{result.final_decision}</span>
              </span>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={reset}>
              <RotateCcw />
              Reset
            </Button>
            <Button type="button" disabled={!canSubmit || simulation.isPending} onClick={submit}>
              <Play />
              {simulation.isPending ? "Running..." : "Run simulation"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function buildSimulationRequest(
  form: SimulationFormState,
  drafts: PolicySimulationDraft[],
): PolicySimulationRequest {
  const promptText = form.promptText.trim();
  const responseText = form.responseText.trim();

  return {
    target: { virtual_key_id: form.virtualKeyId.trim() },
    requested_model: form.requestedModel.trim(),
    gateway_endpoint: form.gatewayEndpoint,
    streaming: form.streaming,
    provider_id: emptyToNull(form.providerId),
    estimated_input_tokens: parseOptionalInteger(form.estimatedInputTokens) ?? 0,
    requested_output_tokens: parseOptionalInteger(form.requestedOutputTokens),
    include_limits: form.includeLimits,
    include_guardrails: form.includeGuardrails,
    evaluate_all_route_candidates: form.evaluateAllRouteCandidates,
    guardrail_input:
      promptText || responseText
        ? {
            prompt_text: promptText || null,
            response_text: responseText || null,
          }
        : null,
    drafts,
  };
}

function setFormField<Key extends keyof SimulationFormState>(
  setForm: Dispatch<SetStateAction<SimulationFormState>>,
  key: Key,
  value: SimulationFormState[Key],
) {
  setForm((current) => ({ ...current, [key]: value }));
}

function parseOptionalInteger(value: string) {
  if (value.trim() === "") return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function emptyToNull(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function ToggleField({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2 text-sm">
      <span className="font-medium">{label}</span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </label>
  );
}
