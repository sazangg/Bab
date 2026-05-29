import { ListRestart, Send, TerminalSquare } from "lucide-react";
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
import { useListUsageRecordsApiV1UsageRecordsGet } from "@/shared/api/generated/usage/usage";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

type PlaygroundResult = {
  status: number;
  body: unknown;
  streamedText?: string;
  rawStream?: string;
};

type GatewayModel = {
  id: string;
  provider_id?: string;
  allocation_id?: string;
  pool_id?: string;
};

export function PlaygroundPage() {
  const [virtualKey, setVirtualKey] = useState("");
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("Reply with pong.");
  const [temperature, setTemperature] = useState("0.2");
  const [maxCompletionTokens, setMaxCompletionTokens] = useState("64");
  const [stream, setStream] = useState(false);
  const [models, setModels] = useState<GatewayModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [requestCount, setRequestCount] = useState(0);

  const usageQuery = useListUsageRecordsApiV1UsageRecordsGet(
    { limit: 1, window: "24h" },
    {
      query: {
        enabled: requestCount > 0,
        retry: false,
      },
    },
  );
  const latestUsage = usageQuery.data?.status === 200 ? usageQuery.data.data[0] : null;

  const canSend =
    virtualKey.trim().length > 0 && model.trim().length > 0 && prompt.trim().length > 0;
  const canLoadModels = virtualKey.trim().length > 0;

  async function loadModels() {
    if (!canLoadModels) return;
    setIsLoadingModels(true);
    try {
      const response = await fetch(resolveGatewayUrl("/v1/models"), {
        headers: {
          Authorization: `Bearer ${virtualKey.trim()}`,
        },
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(extractGatewayMessage(body) ?? `Model request failed: ${response.status}`);
      }
      const nextModels = Array.isArray(body.data) ? body.data : [];
      setModels(nextModels);
      if (!model && nextModels[0]?.id) setModel(nextModels[0].id);
      toast.success(`Loaded ${nextModels.length} model${nextModels.length === 1 ? "" : "s"}.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load models.");
    } finally {
      setIsLoadingModels(false);
    }
  }

  async function sendRequest() {
    if (!canSend) return;
    setIsSending(true);
    setResult(null);
    try {
      const payload = buildPayload({
        model: model.trim(),
        prompt: prompt.trim(),
        temperature,
        maxCompletionTokens,
        stream,
      });
      const response = await fetch(resolveGatewayUrl("/v1/chat/completions"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${virtualKey.trim()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (stream) {
        const streamed = await readOpenAIStream(response);
        setResult({
          status: response.status,
          body: streamed.parsedError ?? { content: streamed.content },
          streamedText: streamed.content,
          rawStream: streamed.raw,
        });
        setRequestCount((value) => value + 1);
        return;
      }
      const text = await response.text();
      let body: unknown = text;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      setResult({ status: response.status, body });
      setRequestCount((value) => value + 1);
    } catch (error) {
      toast.error("Gateway request failed before receiving a response.");
      setResult({ status: 0, body: error instanceof Error ? error.message : String(error) });
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Playground"
        description="Send a simple gateway request with a virtual key and inspect the response."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Request</CardTitle>
            <CardDescription>
              Paste the secret value shown when the virtual key was created.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="playground-key">Virtual key</Label>
              <Input
                id="playground-key"
                type="password"
                value={virtualKey}
                onChange={(event) => setVirtualKey(event.target.value)}
                placeholder="bab-sk-..."
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="playground-model">Model</Label>
              <div className="flex gap-2">
                <Select value={model} onValueChange={setModel}>
                  <SelectTrigger id="playground-model" className="h-10 min-w-0 flex-1">
                    <SelectValue placeholder="Load models or type below" />
                  </SelectTrigger>
                  <SelectContent className="w-[min(34rem,var(--radix-select-trigger-width))]">
                    {models.map((entry) => (
                      <SelectItem key={entry.id} value={entry.id}>
                        {entry.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!canLoadModels || isLoadingModels}
                  onClick={loadModels}
                >
                  <ListRestart data-icon="inline-start" />
                  {isLoadingModels ? "Loading" : "Load"}
                </Button>
              </div>
              <Input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="Manual model id"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="playground-temperature">Temperature</Label>
                <Input
                  id="playground-temperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={temperature}
                  onChange={(event) => setTemperature(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="playground-max-tokens">Max completion tokens</Label>
                <Input
                  id="playground-max-tokens"
                  type="number"
                  min="1"
                  step="1"
                  value={maxCompletionTokens}
                  onChange={(event) => setMaxCompletionTokens(event.target.value)}
                />
              </div>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-md border p-3">
              <div>
                <Label htmlFor="playground-stream">Stream response</Label>
                <p className="text-sm text-muted-foreground">Render chat deltas as SSE arrives.</p>
              </div>
              <Switch id="playground-stream" checked={stream} onCheckedChange={setStream} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="playground-prompt">Prompt</Label>
              <Textarea
                id="playground-prompt"
                rows={7}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
              />
            </div>
            <Button type="button" disabled={!canSend || isSending} onClick={sendRequest}>
              <Send data-icon="inline-start" />
              {isSending ? "Sending..." : "Send request"}
            </Button>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Response</CardTitle>
              <CardDescription>Chat completions response or gateway error.</CardDescription>
            </CardHeader>
            <CardContent>
              {result ? (
                <div className="space-y-3">
                  <div className="text-sm">
                    Status: <span className="font-mono font-medium">{result.status}</span>
                  </div>
                  {result.streamedText !== undefined ? (
                    <div className="rounded-md border bg-background p-3 text-sm leading-6">
                      {result.streamedText || "No streamed content returned."}
                    </div>
                  ) : null}
                  <pre className="max-h-[28rem] overflow-auto rounded-md bg-muted p-3 text-xs">
                    {JSON.stringify(result.body, null, 2)}
                  </pre>
                  {result.rawStream ? (
                    <details className="text-sm">
                      <summary className="cursor-pointer text-muted-foreground">Raw stream</summary>
                      <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
                        {result.rawStream}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ) : (
                <EmptyState
                  icon={TerminalSquare}
                  title="No request sent"
                  description="Send a request to inspect the gateway response here."
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Latest usage record</CardTitle>
              <CardDescription>
                Available for roles that can read organization usage records.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {usageQuery.isFetching ? (
                <p className="text-sm text-muted-foreground">Checking latest usage...</p>
              ) : latestUsage ? (
                <dl className="grid gap-3 text-sm sm:grid-cols-2">
                  <UsageItem label="Status" value={String(latestUsage.http_status)} />
                  <UsageItem label="Model" value={latestUsage.requested_model} />
                  <UsageItem label="Requests" value="1" />
                  <UsageItem label="Tokens" value={String(latestUsage.total_tokens ?? 0)} />
                  <UsageItem
                    label="Cost"
                    value={`$${((latestUsage.cost_cents ?? 0) / 100).toFixed(4)}`}
                  />
                  <UsageItem
                    label="Recorded"
                    value={new Date(latestUsage.created_at).toLocaleString()}
                  />
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No usage record is available for this role or request yet.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function UsageItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function resolveGatewayUrl(path: string) {
  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl ? new URL(path, apiBaseUrl).toString() : path;
}

function buildPayload({
  model,
  prompt,
  temperature,
  maxCompletionTokens,
  stream,
}: {
  model: string;
  prompt: string;
  temperature: string;
  maxCompletionTokens: string;
  stream: boolean;
}) {
  const payload: Record<string, unknown> = {
    model,
    messages: [{ role: "user", content: prompt }],
    stream,
  };
  const parsedTemperature = Number(temperature);
  if (Number.isFinite(parsedTemperature)) payload.temperature = parsedTemperature;
  const parsedMaxCompletionTokens = Number(maxCompletionTokens);
  if (Number.isInteger(parsedMaxCompletionTokens) && parsedMaxCompletionTokens > 0) {
    payload.max_completion_tokens = parsedMaxCompletionTokens;
  }
  return payload;
}

async function readOpenAIStream(response: Response) {
  if (!response.body) {
    const body = await response.text();
    return { content: "", raw: body, parsedError: parseJson(body) };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let raw = "";
  let content = "";
  let parsedError: unknown;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    raw += chunk;
    const parsed = parseStreamChunk(chunk);
    content += parsed.content;
    if (parsed.error) parsedError = parsed.error;
  }

  return { content, raw, parsedError };
}

function parseStreamChunk(chunk: string) {
  let content = "";
  let error: unknown;
  for (const line of chunk.split(/\r?\n/)) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (!data || data === "[DONE]") continue;
    const json = parseJson(data);
    if (!json || typeof json !== "object") continue;
    if ("error" in json) {
      error = json;
      continue;
    }
    const choices = "choices" in json && Array.isArray(json.choices) ? json.choices : [];
    for (const choice of choices) {
      const delta = choice?.delta?.content;
      if (typeof delta === "string") content += delta;
    }
  }
  return { content, error };
}

function parseJson(value: string): unknown {
  try {
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

function extractGatewayMessage(body: unknown) {
  if (!body || typeof body !== "object") return null;
  if ("error" in body && body.error && typeof body.error === "object" && "message" in body.error) {
    return String(body.error.message);
  }
  if ("detail" in body) return String(body.detail);
  return null;
}
