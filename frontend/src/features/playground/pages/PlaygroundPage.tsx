import { Send, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useListUsageRecordsApiV1UsageRecordsGet } from "@/shared/api/generated/usage/usage";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

type PlaygroundResult = {
  status: number;
  body: unknown;
};

export function PlaygroundPage() {
  const [virtualKey, setVirtualKey] = useState("");
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("Reply with pong.");
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

  async function sendRequest() {
    if (!canSend) return;
    setIsSending(true);
    setResult(null);
    try {
      const response = await fetch(resolveGatewayUrl("/v1/chat/completions"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${virtualKey.trim()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: model.trim(),
          messages: [{ role: "user", content: prompt.trim() }],
        }),
      });
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
              <Input
                id="playground-model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="gpt-4o-mini"
              />
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
                  <pre className="max-h-[28rem] overflow-auto rounded-md bg-muted p-3 text-xs">
                    {JSON.stringify(result.body, null, 2)}
                  </pre>
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
