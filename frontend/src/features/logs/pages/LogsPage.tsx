import { ChevronRight, ScrollText } from "lucide-react";
import { useQueryState } from "nuqs";
import { useMemo, useState } from "react";

import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListRequestLogsApiV1RequestLogsGet } from "@/shared/api/generated/request-logs/request-logs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";
import { PageHeader } from "@/shared/components/PageHeader";

export function LogsPage() {
  const [projectId, setProjectId] = useQueryState("project");
  const [providerId, setProviderId] = useQueryState("provider");
  const [virtualKeyId, setVirtualKeyId] = useQueryState("key");
  const [statusCode, setStatusCode] = useQueryState("status");
  const [model, setModel] = useQueryState("model");
  const [providerModel, setProviderModel] = useQueryState("provider_model");
  const [pageParam, setPageParam] = useQueryState("page", { defaultValue: "1" });
  const pageSize = 50;
  const page = Math.max(Number(pageParam) || 1, 1);

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];

  const params = useMemo(() => {
    const result: Record<string, string | number> = { limit: pageSize, offset: (page - 1) * pageSize };
    if (projectId) result.project_id = projectId;
    if (providerId) result.provider_id = providerId;
    if (virtualKeyId) result.virtual_key_id = virtualKeyId;
    if (statusCode) result.status_code = Number(statusCode);
    if (model) result.requested_model = model;
    if (providerModel) result.provider_model = providerModel;
    return result;
  }, [model, page, projectId, providerId, providerModel, statusCode, virtualKeyId]);

  const logsQuery = useListRequestLogsApiV1RequestLogsGet(params);
  const logs = logsQuery.data?.status === 200 ? logsQuery.data.data : [];

  return (
    <>
      <PageHeader
        title="Request logs"
        description="Every proxied LLM call. Click a row to inspect."
      />

      <div className="grid gap-3 rounded-lg border bg-card p-4 md:grid-cols-3 xl:grid-cols-6">
        <FilterField label="Project">
          <Select
            value={projectId ?? "__all"}
            onValueChange={(value) => {
              setProjectId(value === "__all" ? null : value);
              setPageParam("1");
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">All projects</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Provider">
          <Select
            value={providerId ?? "__all"}
            onValueChange={(value) => {
              setProviderId(value === "__all" ? null : value);
              setPageParam("1");
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">All providers</SelectItem>
              {providers.map((provider) => (
                <SelectItem key={provider.id} value={provider.id}>
                  {provider.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Status">
          <Select
            value={statusCode ?? "__all"}
            onValueChange={(value) => {
              setStatusCode(value === "__all" ? null : value);
              setPageParam("1");
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">All</SelectItem>
              <SelectItem value="200">200 OK</SelectItem>
              <SelectItem value="401">401 Unauthorized</SelectItem>
              <SelectItem value="403">403 Forbidden</SelectItem>
              <SelectItem value="429">429 Rate limited</SelectItem>
              <SelectItem value="502">502 Upstream</SelectItem>
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Virtual key">
          <Input
            value={virtualKeyId ?? ""}
            placeholder="Key id"
            onChange={(event) => {
              setVirtualKeyId(event.target.value || null);
              setPageParam("1");
            }}
          />
        </FilterField>
        <FilterField label="Model">
          <Input
            value={model ?? ""}
            placeholder="gpt-4o"
            onChange={(event) => {
              setModel(event.target.value || null);
              setPageParam("1");
            }}
          />
        </FilterField>
        <FilterField label="Provider model">
          <Input
            value={providerModel ?? ""}
            placeholder="gpt-4o-mini"
            onChange={(event) => {
              setProviderModel(event.target.value || null);
              setPageParam("1");
            }}
          />
        </FilterField>
      </div>

      {logsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading request logs...</p>
      ) : logs.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="No requests match these filters"
          description="Try clearing filters or send a request through the gateway."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[1%]" />
                <TableHead>Time</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Usage</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((log) => (
                <LogRow
                  key={log.id}
                  log={log}
                  projectName={
                    projects.find((p) => p.id === log.project_id)?.name ?? "—"
                  }
                  providerName={
                    providers.find((p) => p.id === log.provider_id)?.name ?? "—"
                  }
                />
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between border-t px-4 py-3">
            <p className="text-sm text-muted-foreground">
              Page {page} · showing {logs.length} request{logs.length === 1 ? "" : "s"}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1 || logsQuery.isFetching}
                onClick={() => setPageParam(String(page - 1))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={logs.length < pageSize || logsQuery.isFetching}
                onClick={() => setPageParam(String(page + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

type LogRowProps = {
  log: {
    id: string;
    created_at: string;
    http_status: number;
    project_id: string;
    provider_id: string;
    virtual_key_id: string;
    requested_model: string;
    provider_model: string;
    total_tokens: number | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    latency_ms: number;
    usage_source: string;
    error_code: string | null;
  };
  projectName: string;
  providerName: string;
};

function LogRow({ log, projectName, providerName }: LogRowProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TableRow className="cursor-pointer" onClick={() => setOpen((value) => !value)}>
        <TableCell className="w-[1%]">
          <ChevronRight
            className={`size-3.5 text-muted-foreground transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </TableCell>
        <TableCell className="text-muted-foreground tabular-nums">
          {new Date(log.created_at).toLocaleString()}
        </TableCell>
        <TableCell>
          <HttpStatusBadge status={log.http_status} />
        </TableCell>
        <TableCell>{projectName}</TableCell>
        <TableCell>{providerName}</TableCell>
        <TableCell className="font-mono text-xs">{log.requested_model}</TableCell>
        <TableCell className="text-muted-foreground">{log.usage_source}</TableCell>
        <TableCell className="text-right tabular-nums">{log.total_tokens ?? "—"}</TableCell>
        <TableCell className="text-right tabular-nums">{log.latency_ms} ms</TableCell>
      </TableRow>
      {open ? (
        <TableRow className="bg-muted/30">
          <TableCell />
          <TableCell colSpan={8}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs md:grid-cols-4">
              <Detail label="Provider model" value={log.provider_model} mono />
              <Detail label="Prompt tokens" value={log.prompt_tokens?.toString() ?? "—"} />
              <Detail
                label="Completion tokens"
                value={log.completion_tokens?.toString() ?? "—"}
              />
              <Detail label="Error" value={log.error_code ?? "—"} />
              <Detail label="Virtual key" value={log.virtual_key_id} mono />
              <Detail label="Request ID" value={log.id} mono />
            </dl>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-xs break-all" : "text-sm"}>{value}</dd>
    </div>
  );
}
