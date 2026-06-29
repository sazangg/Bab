import { Eye, ListRestart, LoaderCircle, Send, TerminalSquare } from "lucide-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  type PlaygroundMode,
  validateMaxTokens,
  validateTemperature,
} from "@/features/playground/lib/validation";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListVirtualKeyInventoryApiV1VirtualKeysGet } from "@/shared/api/generated/virtual-keys/virtual-keys";
import type { UsageRecordPageResponse } from "@/shared/api/generated/schemas";
import { apiMutator } from "@/shared/api/orval-mutator";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { HttpStatusBadge, StatusBadge } from "@/shared/components/StatusBadge";
import { RequestTraceSheet } from "@/features/usage/components/RequestTraceSheet";

type PlaygroundResult = {
  status: number;
  body: unknown;
  requestId?: string | null;
  streamedText?: string;
  rawStream?: string;
};
type GatewayModel = {
  id: string;
  provider_id: string;
  provider_name: string;
  candidates?: {
    provider_id: string;
    provider_name: string;
    provider_model: string;
  }[];
};
type UsageRecordsResponse = {
  data: UsageRecordPageResponse;
  status: number;
  headers: Headers;
};
type ResponseView = "message" | "raw";
type MessageFormat = "text" | "markdown" | "json";
const AUTO_PROVIDER = "__auto__";

export function PlaygroundPage() {
  const [searchParams] = useSearchParams();
  const [mode, setMode] = useState<PlaygroundMode>("chat");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedKeyId, setSelectedKeyId] = useState("");
  const [virtualKey, setVirtualKey] = useState("");
  const [model, setModel] = useState(searchParams.get("model") ?? "");
  const [providerId, setProviderId] = useState("");
  const [prompt, setPrompt] = useState("Reply with pong.");
  const [temperature, setTemperature] = useState("0.2");
  const [maxTokens, setMaxTokens] = useState("64");
  const [stream, setStream] = useState(false);
  const [models, setModels] = useState<GatewayModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null);

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const keysQuery = useListVirtualKeyInventoryApiV1VirtualKeysGet(
    selectedProjectId ? { project_id: selectedProjectId, limit: 100 } : undefined,
    { query: { enabled: Boolean(selectedProjectId), retry: false } },
  );
  const usageLookupRequestId = result?.requestId ?? requestId;
  const usageQuery = useQuery({
    queryKey: ["playground-usage", usageLookupRequestId],
    queryFn: () => {
      const params = new URLSearchParams({
        window: "24h",
        limit: "1",
        request_id: usageLookupRequestId!,
      });
      return apiMutator<UsageRecordsResponse>(`/api/v1/usage/records?${params}`, {
        method: "GET",
      });
    },
    enabled: Boolean(usageLookupRequestId),
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: (query) => {
      if (query.state.status === "error") return false;
      if (query.state.dataUpdateCount >= 20) return false;
      return query.state.data?.status === 200 && query.state.data.data.items.length > 0
        ? false
        : 500;
    },
  });
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const keysPage = keysQuery.data?.status === 200 ? keysQuery.data.data : null;
  const projectKeys = keysPage?.items ?? [];
  const selectedKey = projectKeys.find((key) => key.id === selectedKeyId) ?? null;
  const latestUsage = usageQuery.data?.status === 200 ? usageQuery.data.data.items[0] : null;
  const temperatureError = validateTemperature(temperature, mode);
  const maxTokensError = validateMaxTokens(maxTokens, mode);
  const canLoadModels = virtualKey.trim().length > 0;
  const canSend =
    canLoadModels &&
    model.trim().length > 0 &&
    prompt.trim().length > 0 &&
    !temperatureError &&
    !maxTokensError;
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
      if (!model && nextModels[0]?.id) {
        setModel(nextModels[0].id);
      }
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
    const nextRequestId = crypto.randomUUID();
    setRequestId(nextRequestId);
    try {
      const headers: Record<string, string> = {
        "X-Request-ID": nextRequestId,
      };
      if (providerId) {
        headers["X-Bab-Provider-Id"] = providerId;
      }
      const response = await gatewayFetch(endpointForMode(mode), virtualKey, {
        method: "POST",
        headers,
        body: JSON.stringify(buildPayload({ mode, model, prompt, temperature, maxTokens, stream })),
      });
      if (mode === "chat" && stream) {
        const responseRequestId = extractRequestId(response, null);
        setResult({
          status: response.status,
          body: { content: "" },
          requestId: responseRequestId,
          streamedText: "",
          rawStream: "",
        });
        const streamed = await readOpenAIStream(response, (next) => {
          setResult({
            status: response.status,
            body: next.parsedError ?? { content: next.content },
            requestId:
              responseRequestId ?? extractRequestId(response, next.parsedError ?? next.raw),
            streamedText: next.content,
            rawStream: next.raw,
          });
        });
        setResult({
          status: response.status,
          body: streamed.parsedError ?? { content: streamed.content },
          requestId:
            responseRequestId ?? extractRequestId(response, streamed.parsedError ?? streamed.raw),
          streamedText: streamed.content,
          rawStream: streamed.raw,
        });
      } else {
        const text = await response.text();
        const body = parseJson(text) ?? text;
        setResult({ status: response.status, body, requestId: extractRequestId(response, body) });
      }
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

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Settings</CardTitle>
              <CardDescription>
                Choose the endpoint, key, model, and generation controls.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Tabs value={mode} onValueChange={(value) => setMode(value as PlaygroundMode)}>
                <TabsList>
                  <TabsTrigger value="chat">Chat</TabsTrigger>
                  <TabsTrigger value="responses">Responses</TabsTrigger>
                  <TabsTrigger value="completions">Completions</TabsTrigger>
                  <TabsTrigger value="embeddings" disabled>
                    Embeddings
                  </TabsTrigger>
                </TabsList>
                <TabsContent value={mode} className="space-y-4 pt-4">
                  <PlaygroundSettings
                    virtualKey={virtualKey}
                    projects={projects}
                    projectKeys={projectKeys}
                    selectedProjectId={selectedProjectId}
                    selectedKeyId={selectedKeyId}
                    selectedKey={selectedKey}
                    model={model}
                    providerId={providerId}
                    models={models}
                    temperature={temperature}
                    maxTokens={maxTokens}
                    temperatureError={temperatureError}
                    maxTokensError={maxTokensError}
                    stream={stream}
                    supportsStream={supportsStream}
                    isLoadingModels={isLoadingModels}
                    onVirtualKeyChange={setVirtualKey}
                    onProjectChange={(projectId) => {
                      setSelectedProjectId(projectId);
                      setSelectedKeyId("");
                    }}
                    onKeyChange={setSelectedKeyId}
                    onModelChange={(value) => {
                      setModel(value);
                    }}
                    onProviderChange={setProviderId}
                    onTemperatureChange={setTemperature}
                    onMaxTokensChange={setMaxTokens}
                    onStreamChange={setStream}
                    onLoadModels={loadModels}
                    canLoadModels={canLoadModels}
                  />
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Input</CardTitle>
              <CardDescription>Prompt body sent to the selected gateway endpoint.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                id="playground-prompt"
                rows={12}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
              />
              <Button type="button" disabled={!canSend || isSending} onClick={sendRequest}>
                <Send data-icon="inline-start" />
                {isSending ? "Sending..." : `Send ${mode}`}
              </Button>
            </CardContent>
          </Card>
          <ResponseCard result={result} mode={mode} isSending={isSending} />
          <LatestUsageCard
            latestUsage={latestUsage}
            isFetching={usageQuery.isFetching}
            isWaiting={Boolean(usageLookupRequestId && !latestUsage && !usageQuery.isError)}
            requestId={usageLookupRequestId}
            onOpenTrace={(gatewayRequestId) => setTraceRequestId(gatewayRequestId)}
          />
        </div>
      </div>
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

function PlaygroundSettings({
  virtualKey,
  projects,
  projectKeys,
  selectedProjectId,
  selectedKeyId,
  selectedKey,
  model,
  providerId,
  models,
  temperature,
  maxTokens,
  temperatureError,
  maxTokensError,
  stream,
  supportsStream,
  isLoadingModels,
  canLoadModels,
  onVirtualKeyChange,
  onProjectChange,
  onKeyChange,
  onModelChange,
  onProviderChange,
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
  providerId: string;
  models: GatewayModel[];
  temperature: string;
  maxTokens: string;
  temperatureError: string | null;
  maxTokensError: string | null;
  stream: boolean;
  supportsStream: boolean;
  isLoadingModels: boolean;
  canLoadModels: boolean;
  onVirtualKeyChange: (value: string) => void;
  onProjectChange: (value: string) => void;
  onKeyChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onProviderChange: (value: string) => void;
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
          <Label htmlFor="playground-key-select">Key context</Label>
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
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>Prefix: {selectedKey.key_prefix}...</span>
            <span className="inline-flex items-center gap-1.5">
              Status:{" "}
              <StatusBadge
                variant={
                  selectedKey.is_usable ? "active" : selectedKey.revoked_at ? "revoked" : "warning"
                }
              >
                {keyStateLabel(selectedKey)}
              </StatusBadge>
            </span>
            {selectedKey.expires_at ? (
              <span>Expires: {new Date(selectedKey.expires_at).toLocaleString()}</span>
            ) : null}
          </div>
          <p className="mt-2">
            This selection scopes context and usage matching. The pasted secret below authenticates
            the gateway request.
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
                  {entry.candidates && entry.candidates.length > 1
                    ? ` (${entry.candidates.length} candidates)`
                    : ""}
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
      <div className="space-y-1.5">
        <Label htmlFor="playground-provider">Provider</Label>
        <Select
          value={providerId || AUTO_PROVIDER}
          onValueChange={(value) => onProviderChange(value === AUTO_PROVIDER ? "" : value)}
        >
          <SelectTrigger id="playground-provider">
            <SelectValue placeholder="Select an explicit provider" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO_PROVIDER}>Auto</SelectItem>
            {providerOptions(models).map(([id, name]) => (
              <SelectItem key={id} value={id}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Explicit provider mode pins the request to that provider.
        </p>
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
            aria-invalid={Boolean(temperatureError)}
            aria-describedby={temperatureError ? "playground-temperature-error" : undefined}
          />
          {temperatureError ? (
            <p id="playground-temperature-error" className="text-xs text-destructive">
              {temperatureError}
            </p>
          ) : null}
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
            aria-invalid={Boolean(maxTokensError)}
            aria-describedby={maxTokensError ? "playground-max-tokens-error" : undefined}
          />
          {maxTokensError ? (
            <p id="playground-max-tokens-error" className="text-xs text-destructive">
              {maxTokensError}
            </p>
          ) : null}
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
    </>
  );
}

function ResponseCard({
  result,
  mode,
  isSending,
}: {
  result: PlaygroundResult | null;
  mode: PlaygroundMode;
  isSending: boolean;
}) {
  const [view, setView] = useState<ResponseView>("message");
  const [messageFormat, setMessageFormat] = useState<MessageFormat>("text");
  const message = result ? extractResponseMessage(result, mode) : "";
  const parsedMessageJson = parseJson(message);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Response
          {isSending ? (
            <LoaderCircle className="size-4 animate-spin text-muted-foreground" />
          ) : null}
        </CardTitle>
        <CardDescription>{mode} response or gateway error.</CardDescription>
      </CardHeader>
      <CardContent>
        {result ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              Status:{" "}
              {result.status > 0 ? (
                <HttpStatusBadge status={result.status} />
              ) : (
                <StatusBadge variant="error">Failed</StatusBadge>
              )}
            </div>
            {result.requestId ? (
              <div className="text-sm">
                Request ID: <span className="font-mono font-medium">{result.requestId}</span>
              </div>
            ) : null}
            <Tabs value={view} onValueChange={(value) => setView(value as ResponseView)}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <TabsList>
                  <TabsTrigger value="message">Message</TabsTrigger>
                  <TabsTrigger value="raw">Raw JSON</TabsTrigger>
                </TabsList>
                {view === "message" ? (
                  <ToggleGroup
                    type="single"
                    value={messageFormat}
                    onValueChange={(value) => value && setMessageFormat(value as MessageFormat)}
                    className="w-fit"
                  >
                    <ToggleGroupItem value="text">Text</ToggleGroupItem>
                    <ToggleGroupItem value="markdown">Markdown</ToggleGroupItem>
                    <ToggleGroupItem value="json">JSON</ToggleGroupItem>
                  </ToggleGroup>
                ) : null}
              </div>
              <TabsContent value="message" className="pt-3">
                <MessagePanel
                  message={message}
                  parsedJson={parsedMessageJson}
                  format={messageFormat}
                  isSending={isSending}
                />
              </TabsContent>
              <TabsContent value="raw" className="space-y-3 pt-3">
                <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 text-xs">
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
              </TabsContent>
            </Tabs>
          </div>
        ) : isSending ? (
          <div className="flex min-h-48 items-center justify-center rounded-md border bg-muted/20">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <LoaderCircle className="size-5 animate-spin" />
              Waiting for gateway response...
            </div>
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

function MessagePanel({
  message,
  parsedJson,
  format,
  isSending,
}: {
  message: string;
  parsedJson: unknown;
  format: MessageFormat;
  isSending: boolean;
}) {
  if (!message && isSending) {
    return (
      <div className="min-h-24 rounded-md border bg-background p-3 text-sm leading-6">
        <span className="inline-flex items-center gap-2 text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" />
          Waiting for streamed content...
        </span>
      </div>
    );
  }

  if (format === "json") {
    return (
      <pre className="max-h-[32rem] min-h-24 overflow-auto rounded-md border bg-background p-3 text-xs">
        {parsedJson !== null ? JSON.stringify(parsedJson, null, 2) : "Message is not valid JSON."}
      </pre>
    );
  }

  if (format === "markdown") {
    return (
      <div className="max-h-[32rem] min-h-24 overflow-auto rounded-md border bg-background p-3 text-sm leading-6">
        {message ? renderBasicMarkdown(message) : "No message content returned."}
      </div>
    );
  }

  return (
    <div className="max-h-[32rem] min-h-24 overflow-auto whitespace-pre-wrap rounded-md border bg-background p-3 text-sm leading-6">
      {message || "No message content returned."}
    </div>
  );
}

function extractResponseMessage(result: PlaygroundResult, mode: PlaygroundMode) {
  if (typeof result.streamedText === "string") return result.streamedText;
  const body = result.body;
  if (!body || typeof body !== "object") return typeof body === "string" ? body : "";

  if (mode === "responses") {
    const outputText = getStringProperty(body, "output_text");
    if (outputText) return outputText;
    const output = getArrayProperty(body, "output");
    const parts = output.flatMap((item) =>
      getArrayProperty(item, "content").map((content) => getStringProperty(content, "text")),
    );
    return parts.filter(Boolean).join("\n");
  }

  const choices = getArrayProperty(body, "choices");
  if (mode === "completions") {
    return choices
      .map((choice) => getStringProperty(choice, "text"))
      .filter(Boolean)
      .join("\n");
  }

  return choices
    .map((choice) => {
      const message = getObjectProperty(choice, "message");
      const content = message ? getProperty(message, "content") : null;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .map((part) => getStringProperty(part, "text"))
          .filter(Boolean)
          .join("\n");
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function renderBasicMarkdown(markdown: string) {
  const nodes: ReactNode[] = [];
  const lines = markdown.split(/\r?\n/);
  let codeLines: string[] = [];
  let inCode = false;
  let listItems: ReactNode[] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    nodes.push(
      <ul key={`list-${nodes.length}`} className="ml-5 list-disc space-y-1">
        {listItems}
      </ul>,
    );
    listItems = [];
  };
  const flushCode = () => {
    if (!inCode) return;
    nodes.push(
      <pre
        key={`code-${nodes.length}`}
        className="my-2 overflow-auto rounded-md bg-muted p-3 text-xs"
      >
        <code>{codeLines.join("\n")}</code>
      </pre>,
    );
    codeLines = [];
    inCode = false;
  };

  lines.forEach((line, index) => {
    if (line.startsWith("```")) {
      if (inCode) {
        flushCode();
      } else {
        flushList();
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }
    if (!line.trim()) {
      flushList();
      return;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushList();
      const HeadingTag = `h${heading[1].length + 2}` as "h3" | "h4" | "h5";
      nodes.push(
        <HeadingTag key={`heading-${index}`} className="mt-3 font-medium first:mt-0">
          {heading[2]}
        </HeadingTag>,
      );
      return;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      listItems.push(<li key={`item-${index}`}>{renderInlineMarkdown(bullet[1])}</li>);
      return;
    }
    flushList();
    nodes.push(<p key={`p-${index}`}>{renderInlineMarkdown(line)}</p>);
  });
  flushCode();
  flushList();
  return nodes.length > 0 ? nodes : markdown;
}

function renderInlineMarkdown(value: string) {
  const parts = value.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={index} className="rounded bg-muted px-1 py-0.5 text-xs">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function getProperty(value: unknown, key: string): unknown {
  return value && typeof value === "object" ? (value as Record<string, unknown>)[key] : null;
}

function getObjectProperty(value: unknown, key: string) {
  const property = getProperty(value, key);
  return property && typeof property === "object" && !Array.isArray(property) ? property : null;
}

function getArrayProperty(value: unknown, key: string) {
  const property = getProperty(value, key);
  return Array.isArray(property) ? property : [];
}

function getStringProperty(value: unknown, key: string) {
  const property = getProperty(value, key);
  return typeof property === "string" ? property : "";
}

function LatestUsageCard({
  latestUsage,
  isFetching,
  isWaiting,
  requestId,
  onOpenTrace,
}: {
  latestUsage:
    | {
        http_status: number;
        requested_model: string;
        total_tokens?: number | null;
        cost_cents?: number | null;
        request_id?: string | null;
        gateway_request_id?: string | null;
        created_at: string;
      }
    | null
    | undefined;
  isFetching: boolean;
  isWaiting: boolean;
  requestId?: string | null;
  onOpenTrace: (gatewayRequestId: string) => void;
}) {
  const isMatchingRecord = Boolean(requestId && latestUsage?.request_id === requestId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Matching usage record</CardTitle>
        <CardDescription>
          {isMatchingRecord
            ? "Matched by request ID from the gateway response."
            : "Looking up the exact request ID within the selected key context."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {latestUsage ? (
          <div className="space-y-4">
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <UsageItem label="Status" value={String(latestUsage.http_status)} />
              <UsageItem label="Model" value={latestUsage.requested_model} />
              <UsageItem label="Request" value={latestUsage.request_id?.slice(0, 8) ?? "-"} />
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
            {latestUsage.gateway_request_id ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onOpenTrace(latestUsage.gateway_request_id!)}
              >
                <Eye data-icon="inline-start" />
                Open trace
              </Button>
            ) : null}
          </div>
        ) : isWaiting || isFetching ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            Waiting for the usage record for this request...
          </div>
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

async function readOpenAIStream(
  response: Response,
  onProgress?: (state: { content: string; raw: string; parsedError: unknown }) => void,
) {
  if (!response.body) {
    const body = await response.text();
    return { content: "", raw: body, parsedError: parseJson(body) };
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let raw = "";
  let content = "";
  let parsedError: unknown;
  let pending = "";
  while (true) {
    const { done, value } = await reader.read();
    const chunk = done ? decoder.decode() : decoder.decode(value, { stream: true });
    raw += chunk;
    const combined = pending + chunk;
    const lines = combined.split(/\r?\n/);
    pending = done ? "" : (lines.pop() ?? "");
    const parsed = parseStreamLines(lines);
    content += parsed.content;
    if (parsed.error) parsedError = parsed.error;
    onProgress?.({ content, raw, parsedError });
    if (done) break;
  }
  return { content, raw, parsedError };
}

function parseStreamLines(lines: string[]) {
  let content = "";
  let error: unknown;
  for (const line of lines) {
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

function providerOptions(models: GatewayModel[]) {
  return Array.from(
    new Map(
      models.flatMap((entry) =>
        entry.candidates?.length
          ? entry.candidates.map((candidate) => [candidate.provider_id, candidate.provider_name])
          : [[entry.provider_id, entry.provider_name]],
      ),
    ).entries(),
  );
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
