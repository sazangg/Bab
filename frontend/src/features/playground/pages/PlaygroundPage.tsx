import { ListRestart, Send, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListUsageRecordsApiV1UsageRecordsGet } from "@/shared/api/generated/usage/usage";
import { useListVirtualKeyInventoryApiV1VirtualKeysGet } from "@/shared/api/generated/virtual-keys/virtual-keys";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

type PlaygroundMode = "chat" | "responses" | "completions" | "embeddings";
type PlaygroundResult = {
  status: number;
  body: unknown;
  requestId?: string | null;
  streamedText?: string;
  rawStream?: string;
};
type GatewayModel = { id: string };

export function PlaygroundPage() {
  const [searchParams] = useSearchParams();
  const [mode, setMode] = useState<PlaygroundMode>("chat");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedKeyId, setSelectedKeyId] = useState("");
  const [virtualKey, setVirtualKey] = useState("");
  const [model, setModel] = useState(searchParams.get("model") ?? "");
  const [prompt, setPrompt] = useState("Reply with pong.");
  const [temperature, setTemperature] = useState("0.2");
  const [maxTokens, setMaxTokens] = useState("64");
  const [stream, setStream] = useState(false);
  const [models, setModels] = useState<GatewayModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [requestCount, setRequestCount] = useState(0);

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const keysQuery = useListVirtualKeyInventoryApiV1VirtualKeysGet(
    selectedProjectId ? { project_id: selectedProjectId, limit: 100 } : undefined,
    { query: { enabled: Boolean(selectedProjectId), retry: false } },
  );
  const usageQuery = useListUsageRecordsApiV1UsageRecordsGet(
    { limit: 1, window: "24h" },
    { query: { enabled: requestCount > 0, retry: false } },
  );
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const keysPage = keysQuery.data?.status === 200 ? keysQuery.data.data : null;
  const projectKeys = keysPage?.items ?? [];
  const selectedKey = projectKeys.find((key) => key.id === selectedKeyId) ?? null;
  const latestUsage = usageQuery.data?.status === 200 ? usageQuery.data.data[0] : null;
  const canLoadModels = virtualKey.trim().length > 0;
  const canSend = canLoadModels && model.trim().length > 0 && prompt.trim().length > 0;
  const supportsStream = mode === "chat";

  async function loadModels() {
    if (!canLoadModels) return;
    setIsLoadingModels(true);
    try {
      const response = await gatewayFetch("/v1/models", virtualKey);
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
      const response = await gatewayFetch(endpointForMode(mode), virtualKey, {
        method: "POST",
        body: JSON.stringify(buildPayload({ mode, model, prompt, temperature, maxTokens, stream })),
      });
      if (mode === "chat" && stream) {
        const streamed = await readOpenAIStream(response);
        setResult({
          status: response.status,
          body: streamed.parsedError ?? { content: streamed.content },
          requestId: extractRequestId(response, streamed.parsedError ?? streamed.raw),
          streamedText: streamed.content,
          rawStream: streamed.raw,
        });
      } else {
        const text = await response.text();
        const body = parseJson(text) ?? text;
        setResult({ status: response.status, body, requestId: extractRequestId(response, body) });
      }
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
        description="Test gateway-compatible endpoints with a virtual key."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Request</CardTitle>
            <CardDescription>
              Paste the secret value shown when the key was created.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs value={mode} onValueChange={(value) => setMode(value as PlaygroundMode)}>
              <TabsList>
                <TabsTrigger value="chat">Chat</TabsTrigger>
                <TabsTrigger value="responses">Responses</TabsTrigger>
                <TabsTrigger value="completions">Completions</TabsTrigger>
                <TabsTrigger value="embeddings">Embeddings</TabsTrigger>
              </TabsList>
              <TabsContent value={mode} className="space-y-4 pt-2">
                <SharedRequestControls
                  virtualKey={virtualKey}
                  projects={projects}
                  projectKeys={projectKeys}
                  selectedProjectId={selectedProjectId}
                  selectedKeyId={selectedKeyId}
                  selectedKey={selectedKey}
                  model={model}
                  models={models}
                  prompt={prompt}
                  temperature={temperature}
                  maxTokens={maxTokens}
                  stream={stream}
                  supportsStream={supportsStream}
                  isLoadingModels={isLoadingModels}
                  onVirtualKeyChange={setVirtualKey}
                  onProjectChange={(projectId) => {
                    setSelectedProjectId(projectId);
                    setSelectedKeyId("");
                  }}
                  onKeyChange={setSelectedKeyId}
                  onModelChange={setModel}
                  onPromptChange={setPrompt}
                  onTemperatureChange={setTemperature}
                  onMaxTokensChange={setMaxTokens}
                  onStreamChange={setStream}
                  onLoadModels={loadModels}
                  canLoadModels={canLoadModels}
                />
                {mode === "embeddings" ? (
                  <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
                    Embeddings intentionally return 501 until adapter support is implemented.
                  </div>
                ) : null}
                <Button type="button" disabled={!canSend || isSending} onClick={sendRequest}>
                  <Send data-icon="inline-start" />
                  {isSending ? "Sending..." : `Send ${mode}`}
                </Button>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <ResponseCard result={result} mode={mode} />
          <LatestUsageCard
            latestUsage={latestUsage}
            isFetching={usageQuery.isFetching}
            requestId={result?.requestId}
          />
        </div>
      </div>
    </div>
  );
}

function SharedRequestControls({
  virtualKey,
  projects,
  projectKeys,
  selectedProjectId,
  selectedKeyId,
  selectedKey,
  model,
  models,
  prompt,
  temperature,
  maxTokens,
  stream,
  supportsStream,
  isLoadingModels,
  canLoadModels,
  onVirtualKeyChange,
  onProjectChange,
  onKeyChange,
  onModelChange,
  onPromptChange,
  onTemperatureChange,
  onMaxTokensChange,
  onStreamChange,
  onLoadModels,
}: {
  virtualKey: string;
  projects: { id: string; name: string; is_active: boolean }[];
  projectKeys: {
    id: string;
    name: string;
    key_prefix: string;
    status: string;
    is_usable: boolean;
    project_is_active: boolean;
    team_is_active: boolean;
    expires_at: string | null;
    revoked_at: string | null;
  }[];
  selectedProjectId: string;
  selectedKeyId: string;
  selectedKey: {
    name: string;
    key_prefix: string;
    status: string;
    is_usable: boolean;
    project_is_active: boolean;
    team_is_active: boolean;
    expires_at: string | null;
    revoked_at: string | null;
  } | null;
  model: string;
  models: GatewayModel[];
  prompt: string;
  temperature: string;
  maxTokens: string;
  stream: boolean;
  supportsStream: boolean;
  isLoadingModels: boolean;
  canLoadModels: boolean;
  onVirtualKeyChange: (value: string) => void;
  onProjectChange: (value: string) => void;
  onKeyChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onPromptChange: (value: string) => void;
  onTemperatureChange: (value: string) => void;
  onMaxTokensChange: (value: string) => void;
  onStreamChange: (value: boolean) => void;
  onLoadModels: () => void;
}) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="playground-project">Project</Label>
          <Select value={selectedProjectId} onValueChange={onProjectChange}>
            <SelectTrigger id="playground-project" className="h-10">
              <SelectValue placeholder="Select project" />
            </SelectTrigger>
            <SelectContent>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                  {!project.is_active ? " (inactive)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="playground-key-select">Virtual key metadata</Label>
          <Select value={selectedKeyId} onValueChange={onKeyChange} disabled={!selectedProjectId}>
            <SelectTrigger id="playground-key-select" className="h-10">
              <SelectValue placeholder="Select key" />
            </SelectTrigger>
            <SelectContent>
              {projectKeys.map((key) => (
                <SelectItem key={key.id} value={key.id}>
                  {key.name} ({key.key_prefix}...)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {selectedKey ? (
        <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
          <div className="font-medium text-foreground">{selectedKey.name}</div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <span>Prefix: {selectedKey.key_prefix}...</span>
            <span>Status: {keyStateLabel(selectedKey)}</span>
            {selectedKey.expires_at ? (
              <span>Expires: {new Date(selectedKey.expires_at).toLocaleString()}</span>
            ) : null}
          </div>
          <p className="mt-2">
            The selector shows safe metadata only. Paste the plaintext secret you already saved to
            send gateway requests.
          </p>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="playground-key">Plaintext key secret</Label>
        <Input
          id="playground-key"
          type="password"
          value={virtualKey}
          onChange={(event) => onVirtualKeyChange(event.target.value)}
          placeholder="bab-sk-..."
        />
        <p className="text-xs text-muted-foreground">
          Secrets cannot be recovered from stored key metadata.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="playground-model">Model</Label>
        <div className="flex gap-2">
          <Select value={model} onValueChange={onModelChange}>
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
            onClick={onLoadModels}
          >
            <ListRestart data-icon="inline-start" />
            {isLoadingModels ? "Loading" : "Load"}
          </Button>
        </div>
        <Input
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
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
            onChange={(event) => onTemperatureChange(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="playground-max-tokens">Max tokens</Label>
          <Input
            id="playground-max-tokens"
            type="number"
            min="1"
            step="1"
            value={maxTokens}
            onChange={(event) => onMaxTokensChange(event.target.value)}
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 rounded-md border p-3">
        <div>
          <Label htmlFor="playground-stream">Stream response</Label>
          <p className="text-sm text-muted-foreground">
            {supportsStream
              ? "Render chat deltas as SSE arrives."
              : "Only chat supports streaming."}
          </p>
        </div>
        <Switch
          id="playground-stream"
          checked={supportsStream && stream}
          disabled={!supportsStream}
          onCheckedChange={onStreamChange}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="playground-prompt">Input</Label>
        <Textarea
          id="playground-prompt"
          rows={7}
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
        />
      </div>
    </>
  );
}

function ResponseCard({ result, mode }: { result: PlaygroundResult | null; mode: PlaygroundMode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Response</CardTitle>
        <CardDescription>{mode} response or gateway error.</CardDescription>
      </CardHeader>
      <CardContent>
        {result ? (
          <div className="space-y-3">
            <div className="text-sm">
              Status: <span className="font-mono font-medium">{result.status}</span>
            </div>
            {result.requestId ? (
              <div className="text-sm">
                Request ID: <span className="font-mono font-medium">{result.requestId}</span>
              </div>
            ) : null}
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
  );
}

function LatestUsageCard({
  latestUsage,
  isFetching,
  requestId,
}: {
  latestUsage:
    | {
        http_status: number;
        requested_model: string;
        total_tokens?: number | null;
        cost_cents?: number | null;
        request_id?: string | null;
        created_at: string;
      }
    | null
    | undefined;
  isFetching: boolean;
  requestId?: string | null;
}) {
  const isMatchingRecord = Boolean(requestId && latestUsage?.request_id === requestId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{isMatchingRecord ? "Matching usage record" : "Recent visible usage"}</CardTitle>
        <CardDescription>
          {isMatchingRecord
            ? "Matched by request ID from the gateway response."
            : "Available for roles that can read usage. Without exact request lookup, this may not be the request just sent."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isFetching ? (
          <p className="text-sm text-muted-foreground">Checking recent usage...</p>
        ) : latestUsage ? (
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <UsageItem label="Status" value={String(latestUsage.http_status)} />
            <UsageItem label="Model" value={latestUsage.requested_model} />
            <UsageItem label="Request" value={latestUsage.request_id?.slice(0, 8) ?? "-"} />
            <UsageItem label="Tokens" value={String(latestUsage.total_tokens ?? 0)} />
            <UsageItem
              label="Cost"
              value={`$${((latestUsage.cost_cents ?? 0) / 100).toFixed(4)}`}
            />
            <UsageItem label="Recorded" value={new Date(latestUsage.created_at).toLocaleString()} />
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            No usage record is available for this role or request yet.
          </p>
        )}
      </CardContent>
    </Card>
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

function endpointForMode(mode: PlaygroundMode) {
  if (mode === "responses") return "/v1/responses";
  if (mode === "completions") return "/v1/completions";
  if (mode === "embeddings") return "/v1/embeddings";
  return "/v1/chat/completions";
}

function buildPayload({
  mode,
  model,
  prompt,
  temperature,
  maxTokens,
  stream,
}: {
  mode: PlaygroundMode;
  model: string;
  prompt: string;
  temperature: string;
  maxTokens: string;
  stream: boolean;
}) {
  const parsedTemperature = Number(temperature);
  const parsedMaxTokens = Number(maxTokens);
  const common: Record<string, unknown> = { model };
  if (Number.isFinite(parsedTemperature) && mode !== "embeddings") {
    common.temperature = parsedTemperature;
  }
  if (mode === "responses") {
    return { ...common, input: prompt, max_output_tokens: tokenValue(parsedMaxTokens) };
  }
  if (mode === "completions") {
    return { ...common, prompt, max_tokens: tokenValue(parsedMaxTokens) };
  }
  if (mode === "embeddings") {
    return { model, input: prompt };
  }
  return {
    ...common,
    messages: [{ role: "user", content: prompt }],
    stream,
    max_completion_tokens: tokenValue(parsedMaxTokens),
  };
}

function tokenValue(value: number) {
  return Number.isInteger(value) && value > 0 ? value : undefined;
}

function gatewayFetch(path: string, virtualKey: string, init: RequestInit = {}) {
  return fetch(resolveGatewayUrl(path), {
    ...init,
    headers: {
      Authorization: `Bearer ${virtualKey.trim()}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
}

function resolveGatewayUrl(path: string) {
  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl ? new URL(path, apiBaseUrl).toString() : path;
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

function keyStateLabel(key: {
  status: string;
  is_usable: boolean;
  project_is_active: boolean;
  team_is_active: boolean;
  revoked_at: string | null;
  expires_at: string | null;
}) {
  if (key.revoked_at) return "revoked";
  if (!key.team_is_active) return "team inactive";
  if (!key.project_is_active) return "project inactive";
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) return "expired";
  if (!key.is_usable) return key.status || "not usable";
  return "usable";
}

function extractRequestId(response: Response, body: unknown) {
  const headerValue = response.headers.get("x-request-id") ?? response.headers.get("request-id");
  if (headerValue) return headerValue;
  return findRequestId(body);
}

function findRequestId(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  if ("request_id" in value && typeof value.request_id === "string") return value.request_id;
  if ("error" in value) return findRequestId(value.error);
  return null;
}
