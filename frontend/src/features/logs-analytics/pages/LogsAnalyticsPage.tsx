import { useQueryState } from "nuqs";

import { useGetAnalyticsSummaryApiV1AnalyticsSummaryGet } from "@/shared/api/generated/analytics/analytics";
import { useListAuditLogsApiV1AuditLogsGet } from "@/shared/api/generated/audit-logs/audit-logs";
import { useListRequestLogsApiV1RequestLogsGet } from "@/shared/api/generated/request-logs/request-logs";

export function LogsAnalyticsPage() {
  const [tab, setTab] = useQueryState("tab", { defaultValue: "analytics" });
  const analyticsQuery = useGetAnalyticsSummaryApiV1AnalyticsSummaryGet({
    days: 7,
    recent_limit: 5,
  });
  const logsQuery = useListRequestLogsApiV1RequestLogsGet({ limit: 50 });
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

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </section>
  );
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
