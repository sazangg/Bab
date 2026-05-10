import { useQueryState } from "nuqs";

import { useGetAnalyticsSummaryApiV1AnalyticsSummaryGet } from "@/shared/api/generated/analytics/analytics";
import { useListAuditLogsApiV1AuditLogsGet } from "@/shared/api/generated/audit-logs/audit-logs";
import { useListRequestLogsApiV1RequestLogsGet } from "@/shared/api/generated/request-logs/request-logs";

export function LogsAnalyticsPage() {
  const [tab, setTab] = useQueryState("tab", { defaultValue: "analytics" });
  const [days, setDays] = useQueryState("days", { defaultValue: "7" });
  const [recentLimit, setRecentLimit] = useQueryState("recent_limit", { defaultValue: "5" });
  const [requestLimit, setRequestLimit] = useQueryState("request_limit", { defaultValue: "50" });
  const [requestOffset, setRequestOffset] = useQueryState("request_offset", {
    defaultValue: "0",
  });
  const [statusCode, setStatusCode] = useQueryState("status");
  const [projectId, setProjectId] = useQueryState("project");
  const [virtualKeyId, setVirtualKeyId] = useQueryState("key");
  const [providerId, setProviderId] = useQueryState("provider");
  const [requestedModel, setRequestedModel] = useQueryState("requested_model");
  const [providerModel, setProviderModel] = useQueryState("provider_model");
  const analyticsDays = clampNumber(days, 7, 1, 90);
  const analyticsRecentLimit = clampNumber(recentLimit, 5, 1, 20);
  const logsLimit = clampNumber(requestLimit, 50, 1, 100);
  const logsOffset = clampNumber(requestOffset, 0, 0);
  const parsedStatusCode = statusCode ? Number(statusCode) : null;
  const analyticsQuery = useGetAnalyticsSummaryApiV1AnalyticsSummaryGet({
    days: analyticsDays,
    recent_limit: analyticsRecentLimit,
  });
  const logsQuery = useListRequestLogsApiV1RequestLogsGet({
    limit: logsLimit,
    offset: logsOffset,
    project_id: projectId || null,
    virtual_key_id: virtualKeyId || null,
    provider_id: providerId || null,
    status_code: parsedStatusCode && parsedStatusCode >= 100 ? parsedStatusCode : null,
    requested_model: requestedModel || null,
    provider_model: providerModel || null,
  });
  const auditLogsQuery = useListAuditLogsApiV1AuditLogsGet({ limit: 50 });
  const analytics = analyticsQuery.data?.status === 200 ? analyticsQuery.data.data : null;
  const requestLogs = logsQuery.data?.status === 200 ? logsQuery.data.data : [];
  const auditLogs = auditLogsQuery.data?.status === 200 ? auditLogsQuery.data.data : [];

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-muted-foreground">Observability</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Logs & analytics</h1>
      </header>

      <div className="flex gap-2">
        {["analytics", "requests", "audit"].map((item) => (
          <button
            key={item}
            type="button"
            className="rounded-md border px-3 py-2 text-sm capitalize data-[active=true]:bg-primary data-[active=true]:text-primary-foreground"
            data-active={tab === item}
            onClick={() => void setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "analytics" ? (
        <section className="space-y-4">
          <div className="grid gap-3 rounded-lg border bg-card p-4 md:grid-cols-[1fr_1fr_auto]">
            <NumberInput
              label="Window days"
              min={1}
              max={90}
              value={analyticsDays}
              onChange={(value) => void setDays(value)}
            />
            <NumberInput
              label="Recent requests"
              min={1}
              max={20}
              value={analyticsRecentLimit}
              onChange={(value) => void setRecentLimit(value)}
            />
            <div className="flex items-end text-sm text-muted-foreground">
              Showing the last {analyticsDays} day{analyticsDays === 1 ? "" : "s"}.
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Requests" value={analytics?.totals.request_count ?? 0} />
            <Metric label="Errors" value={analytics?.totals.error_count ?? 0} />
            <Metric label="Tokens" value={analytics?.totals.total_tokens ?? 0} />
            <Metric label="Avg latency" value={`${analytics?.totals.average_latency_ms ?? 0} ms`} />
          </div>
          <Panel title="Top keys">
            <Table
              headers={["Key", "Requests", "Tokens"]}
              rows={(analytics?.top_keys ?? []).map((key) => [
                key.key_name,
                key.request_count.toString(),
                key.total_tokens.toString(),
              ])}
              empty="No key usage yet."
            />
          </Panel>
          <Panel title="Daily usage">
            <Table
              headers={["Day", "Requests", "Tokens"]}
              rows={(analytics?.time_series ?? []).map((point) => [
                new Date(point.bucket).toLocaleDateString(),
                point.request_count.toString(),
                point.total_tokens.toString(),
              ])}
              empty="No usage buckets yet."
            />
          </Panel>
        </section>
      ) : null}

      {tab === "requests" ? (
        <Panel title="Request logs">
          <div className="mb-4 grid gap-3 lg:grid-cols-4">
            <NumberInput
              label="Limit"
              min={1}
              max={100}
              value={logsLimit}
              onChange={(value) => {
                void setRequestLimit(value);
                void setRequestOffset("0");
              }}
            />
            <NumberInput
              label="Status"
              min={100}
              max={599}
              value={parsedStatusCode && parsedStatusCode >= 100 ? parsedStatusCode : ""}
              onChange={(value) => {
                void setStatusCode(value || null);
                void setRequestOffset("0");
              }}
            />
            <TextInput
              label="Project ID"
              value={projectId ?? ""}
              onChange={(value) => {
                void setProjectId(value || null);
                void setRequestOffset("0");
              }}
            />
            <TextInput
              label="Virtual key ID"
              value={virtualKeyId ?? ""}
              onChange={(value) => {
                void setVirtualKeyId(value || null);
                void setRequestOffset("0");
              }}
            />
            <TextInput
              label="Provider ID"
              value={providerId ?? ""}
              onChange={(value) => {
                void setProviderId(value || null);
                void setRequestOffset("0");
              }}
            />
            <TextInput
              label="Requested model"
              value={requestedModel ?? ""}
              onChange={(value) => {
                void setRequestedModel(value || null);
                void setRequestOffset("0");
              }}
            />
            <TextInput
              label="Provider model"
              value={providerModel ?? ""}
              onChange={(value) => {
                void setProviderModel(value || null);
                void setRequestOffset("0");
              }}
            />
            <div className="flex items-end gap-2">
              <button
                type="button"
                className="h-9 rounded-md border px-3 text-sm disabled:opacity-50"
                disabled={logsOffset === 0}
                onClick={() => void setRequestOffset(String(Math.max(0, logsOffset - logsLimit)))}
              >
                Previous
              </button>
              <button
                type="button"
                className="h-9 rounded-md border px-3 text-sm disabled:opacity-50"
                disabled={requestLogs.length < logsLimit}
                onClick={() => void setRequestOffset(String(logsOffset + logsLimit))}
              >
                Next
              </button>
            </div>
          </div>
          <p className="mb-3 text-sm text-muted-foreground">
            Showing {logsOffset + 1}-{logsOffset + requestLogs.length} with a page size of{" "}
            {logsLimit}.
          </p>
          <Table
            headers={[
              "Time",
              "Status",
              "Model",
              "Provider model",
              "Tokens",
              "Usage source",
              "Error",
            ]}
            rows={requestLogs.map((log) => [
              new Date(log.created_at).toLocaleString(),
              log.http_status.toString(),
              log.requested_model,
              log.provider_model,
              (log.total_tokens ?? 0).toString(),
              log.usage_source,
              log.error_code ?? "",
            ])}
            empty="No request logs yet."
          />
        </Panel>
      ) : null}

      {tab === "audit" ? (
        <Panel title="Audit logs">
          <Table
            headers={["Time", "Event", "Target", "Actor", "Metadata"]}
            rows={auditLogs.map((log) => [
              new Date(log.created_at).toLocaleString(),
              log.event,
              [log.target_type, log.target_id].filter(Boolean).join(" / "),
              log.actor_user_id ?? "",
              log.event_metadata ? JSON.stringify(log.event_metadata) : "",
            ])}
            empty="No audit logs yet."
          />
        </Panel>
      ) : null}
    </div>
  );
}

function NumberInput({
  label,
  min,
  max,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  value: number | "";
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        min={min}
        max={max}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function TextInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        value={value}
        onChange={(event) => onChange(event.target.value.trim())}
      />
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </section>
  );
}

function clampNumber(value: string, fallback: number, min: number, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5">
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Table({ headers, rows, empty }: { headers: string[]; rows: string[][]; empty: string }) {
  return (
    <div className="overflow-auto rounded-md border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted text-muted-foreground">
          <tr>
            {headers.map((header) => (
              <th key={header} className="whitespace-nowrap px-3 py-2 font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.join("-")}-${index}`} className="border-t">
              {row.map((cell, cellIndex) => (
                <td key={`${cell}-${cellIndex}`} className="whitespace-nowrap px-3 py-2">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td className="px-3 py-4 text-muted-foreground" colSpan={headers.length}>
                {empty}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
