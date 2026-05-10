import { useListRequestLogsApiV1RequestLogsGet } from "@/shared/api/generated/request-logs/request-logs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { HttpStatusBadge } from "@/shared/components/StatusBadge";

export function ProjectActivitySection({ projectId }: { projectId: string }) {
  const logsQuery = useListRequestLogsApiV1RequestLogsGet({
    limit: 25,
    project_id: projectId,
  });
  const logs = logsQuery.data?.status === 200 ? logsQuery.data.data : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent activity</CardTitle>
        <CardDescription>Last 25 proxied requests for this project.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Tokens</TableHead>
              <TableHead className="text-right">Latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logsQuery.isPending ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  Loading activity...
                </TableCell>
              </TableRow>
            ) : logs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  No requests yet for this project.
                </TableCell>
              </TableRow>
            ) : (
              logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="text-muted-foreground tabular-nums">
                    {new Date(log.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <HttpStatusBadge status={log.http_status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{log.requested_model}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {log.total_tokens ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{log.latency_ms} ms</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
