import { Copy, ExternalLink, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/shared/components/PageHeader";

const baseUrl = "http://localhost:8000";

export function ApiDocsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="API Docs"
        description="Quick test recipes for the current OpenAI-compatible gateway surface."
      />

      <Card>
        <CardHeader>
          <CardTitle>Current gateway endpoint</CardTitle>
          <CardDescription>
            Use a virtual key from a project. The key is sent as a Bearer token.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <CommandBlock
            title="List key-visible models"
            command={`curl ${baseUrl}/v1/models \\
  -H "Authorization: Bearer bab-sk-..."`}
          />
          <CommandBlock
            title="Chat completions"
            command={`curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer bab-sk-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "Reply with pong"}
    ],
    "max_completion_tokens": 32
  }'`}
          />
          <CommandBlock
            title="Responses compatibility"
            command={`curl ${baseUrl}/v1/responses \\
  -H "Authorization: Bearer bab-sk-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "input": "Reply with pong",
    "max_output_tokens": 32
  }'`}
          />
          <CommandBlock
            title="Legacy completions compatibility"
            command={`curl ${baseUrl}/v1/completions \\
  -H "Authorization: Bearer bab-sk-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "prompt": "Reply with pong",
    "max_tokens": 32
  }'`}
          />
          <div className="rounded-md border bg-muted/20 p-4 text-sm leading-6 text-muted-foreground">
            <div className="font-medium text-foreground">Postman setup</div>
            <p>Method: POST</p>
            <p>URL: {baseUrl}/v1/chat/completions</p>
            <p>Authorization: Bearer Token, using the virtual key as the token.</p>
            <p>Headers: Content-Type application/json.</p>
            <p>Body: raw JSON using the same payload as the curl example.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Notes</CardTitle>
          <CardDescription>
            Known compatibility details while the gateway surface grows.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-6 text-muted-foreground">
          <p>
            Chat completions are the primary proxy endpoint. Streaming is supported there. Responses
            and legacy completions are compatibility adapters over chat completions.
          </p>
          <p>
            Some newer OpenAI models reject <code>max_tokens</code>; use{" "}
            <code>max_completion_tokens</code> when testing those models.
          </p>
          <p>Embeddings require a provider adapter expansion and are not part of this slice yet.</p>
          <Button asChild variant="outline" className="w-fit">
            <a href={`${baseUrl}/openapi.json`} target="_blank" rel="noreferrer">
              <ExternalLink />
              Open raw OpenAPI
            </a>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function CommandBlock({ title, command }: { title: string; command: string }) {
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex items-center justify-between gap-3 border-b bg-muted/30 px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Terminal className="size-4" />
          {title}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => navigator.clipboard.writeText(command)}
        >
          <Copy />
          Copy
        </Button>
      </div>
      <pre className="overflow-auto p-4 text-xs leading-5">
        <code>{command}</code>
      </pre>
    </div>
  );
}
