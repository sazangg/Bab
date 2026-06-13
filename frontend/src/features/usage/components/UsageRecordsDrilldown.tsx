import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useListUsageRecordsApiV1UsageRecordsGet } from "@/shared/api/generated/usage/usage";
import { httpClient } from "@/shared/api/http-client";
import type { UsageRecordResponse } from "@/shared/api/generated/schemas";
import { formatCents } from "@/shared/lib/format-currency";

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
  const records = recordsQuery.data?.status === 200 ? recordsQuery.data.data : [];

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
        {recordsQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading usage records...</p>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No usage records in the last 30 days.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Request</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Spend</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.slice(0, 15).map((record) => (
                <TableRow key={record.id}>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {new Date(record.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{record.requested_model}</div>
                    <div className="text-xs text-muted-foreground">{record.provider_model}</div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">
                      {record.provider_credential_name ?? "Unknown"}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {record.provider_credential_prefix ?? shortId(record.provider_credential_id)}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {shortId(record.request_id)}
                  </TableCell>
                  <TableCell>{record.http_status}</TableCell>
                  <TableCell className="text-right">
                    {formatRecordSpend(record)}
                  </TableCell>
                  <TableCell className="text-right">{record.latency_ms}ms</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
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
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-usage-records.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}

function formatRecordSpend(record: UsageRecordResponse) {
  if (record.spend_type === "unknown") return "Unpriced";
  if (record.spend_type === "confirmed") {
    return `${formatCents(record.confirmed_spend_cents)} reported usage`;
  }
  return `${formatCents(record.estimated_spend_cents)} estimated`;
}
