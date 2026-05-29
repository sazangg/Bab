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
import type { UsageRecordResponse } from "@/shared/api/generated/schemas";

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
          <Button variant="outline" size="sm" onClick={() => downloadCsv(records)}>
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
                  <TableCell>{record.http_status}</TableCell>
                  <TableCell className="text-right">{formatCents(record.cost_cents)}</TableCell>
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

function downloadCsv(records: UsageRecordResponse[]) {
  const header = [
    "created_at",
    "requested_model",
    "provider_model",
    "http_status",
    "total_tokens",
    "cost_cents",
    "latency_ms",
    "provider_credential_id",
    "provider_credential_name",
    "provider_credential_prefix",
    "error_code",
  ];
  const rows = records.map((record) =>
    [
      record.created_at,
      record.requested_model,
      record.provider_model,
      record.http_status,
      record.total_tokens ?? 0,
      record.cost_cents ?? 0,
      record.latency_ms,
      record.provider_credential_id ?? "",
      record.provider_credential_name ?? "",
      record.provider_credential_prefix ?? "",
      record.error_code ?? "",
    ]
      .map((value) => `"${String(value).replaceAll('"', '""')}"`)
      .join(","),
  );
  const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "bab-usage-records.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "-";
}

function formatCents(value: number | null | undefined) {
  return value == null ? "Unpriced" : `$${(value / 100).toLocaleString()}`;
}
