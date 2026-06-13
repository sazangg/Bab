export type ReadinessResponse = {
  status: "ready" | "not_ready";
  checks: Record<
    string,
    {
      ok: boolean;
      error?: string;
      current_revision?: string | null;
      head_revision?: string | null;
    }
  >;
};

export function resolveGatewayStatus(statusCode?: number, readiness?: ReadinessResponse) {
  if (!statusCode || !readiness) {
    return {
      label: "Status unavailable",
      variant: "unknown",
      className: "bg-muted-foreground",
    } as const;
  }
  if (statusCode === 200 && readiness.status === "ready") {
    return {
      label: "Gateway ready",
      variant: "ready",
      className: "bg-success",
    } as const;
  }
  return {
    label: "Gateway degraded",
    variant: "degraded",
    className: "bg-warning",
  } as const;
}

export function formatMigrationStatus(migrations: {
  ok: boolean;
  current_revision?: string | null;
  head_revision?: string | null;
  error?: string | null;
}) {
  if (migrations.error) return `Unavailable: ${migrations.error}`;
  if (migrations.ok) {
    return `Current${migrations.current_revision ? ` (${migrations.current_revision})` : ""}`;
  }
  if (migrations.current_revision || migrations.head_revision) {
    return `Behind: ${migrations.current_revision ?? "unknown"} to ${
      migrations.head_revision ?? "unknown"
    }`;
  }
  return "Needs attention";
}
