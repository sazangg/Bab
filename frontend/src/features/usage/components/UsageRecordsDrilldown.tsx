import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { useListUsageRecordsApiV1UsageRecordsGet } from "@/shared/api/generated/usage/usage";
import { httpClient } from "@/shared/api/http-client";
import type { UsageRecordResponse } from "@/shared/api/generated/schemas";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";
import { downloadBlob } from "@/shared/lib/download";
import { formatCents } from "@/shared/lib/format-currency";
import { shortId } from "@/shared/lib/short-id";

type UsageRecordsDrilldownProps = {
  title?: string;
  filters: {
    team_id?: string;
    provider_id?: string;
    project_id?: string;
    virtual_key_id?: string;
  };
};

export function UsageRecordsDrilldown({
  title = "Usage records",
  filters,
}: UsageRecordsDrilldownProps) {
  const recordsQuery = useListUsageRecordsApiV1UsageRecordsGet({
    window: "30d",
    limit: 100,
    ...filters,
  });
  const records = recordsQuery.data?.status === 200 ? recordsQuery.data.data.items : [];

  const columns: DataTableColumn<UsageRecordResponse>[] = [
    {
      key: "time",
      header: "Time",
      className: "whitespace-nowrap text-muted-foreground",
      cell: (record) => new Date(record.created_at).toLocaleString(),
    },
    {
      key: "model",
      header: "Model",
      cell: (record) => (
        <>
          <div className="font-medium">{record.requested_model}</div>
          <div className="text-xs text-muted-foreground">{record.provider_model}</div>
        </>
      ),
    },
    {
      key: "credential",
      header: "Credential",
      cell: (record) => (
        <>
          <div className="font-medium">{record.provider_credential_name ?? "Unknown"}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {record.provider_credential_prefix ?? shortId(record.provider_credential_id)}
          </div>
        </>
      ),
    },
    {
      key: "request",
      header: "Request",
      className: "font-mono text-xs text-muted-foreground",
      cell: (record) => shortId(record.request_id),
    },
    {
      key: "status",
      header: "Status",
      cell: (record) => <HttpStatusBadge status={record.http_status} />,
    },
    {
      key: "spend",
      header: "Spend",
      align: "right",
      cell: (record) => formatRecordSpend(record),
    },
    {
      key: "latency",
      header: "Latency",
      align: "right",
      cell: (record) => `${record.latency_ms}ms`,
    },
  ];

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Button variant="outline" size="sm" onClick={() => downloadCsv(filters)}>
            <Download data-icon="inline-start" />
            Export CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={records.slice(0, 15)}
          loading={recordsQuery.isPending}
          getRowKey={(record) => record.id}
          empty={{ title: "No usage records in the last 30 days." }}
        />
      </CardContent>
    </Card>
  );
}

async function downloadCsv(filters: UsageRecordsDrilldownProps["filters"]) {
  const response = await httpClient.get<Blob>("/api/v1/usage/records/export", {
    params: {
      window: "30d",
      ...filters,
    },
    responseType: "blob",
  });
  downloadBlob(response.data, "bab-usage-records.csv");
}

function formatRecordSpend(record: UsageRecordResponse) {
  if (record.spend_type === "unknown") return "Unpriced";
  if (record.spend_type === "confirmed") {
    return `${formatCents(record.confirmed_spend_cents)} reported usage`;
  }
  return `${formatCents(record.estimated_spend_cents)} estimated`;
}
