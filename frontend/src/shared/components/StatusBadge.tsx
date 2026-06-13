import { Badge } from "@/components/ui/badge";

export type StatusVariant =
  | "active"
  | "inactive"
  | "revoked"
  | "expired"
  | "success"
  | "error"
  | "muted"
  | "warning"
  | "info";

// Driven entirely by semantic tokens (no raw palette colors) so a status's color is
// defined once in index.css and themed automatically.
const variantClasses: Record<StatusVariant, string> = {
  active: "bg-success/10 text-success border-success/25",
  success: "bg-success/10 text-success border-success/25",
  warning: "bg-warning/10 text-warning border-warning/25",
  expired: "bg-warning/10 text-warning border-warning/25",
  info: "bg-info/10 text-info border-info/25",
  inactive: "bg-muted text-muted-foreground border-border",
  muted: "bg-muted text-muted-foreground border-border",
  revoked: "bg-destructive/10 text-destructive border-destructive/20",
  error: "bg-destructive/10 text-destructive border-destructive/20",
};

export function StatusBadge({
  variant = "muted",
  children,
}: {
  variant?: StatusVariant;
  children: React.ReactNode;
}) {
  return (
    <Badge variant="outline" className={variantClasses[variant]}>
      {children}
    </Badge>
  );
}

export function HttpStatusBadge({ status }: { status: number }) {
  if (status >= 200 && status < 300) {
    return <StatusBadge variant="success">{status}</StatusBadge>;
  }
  if (status >= 400) {
    return <StatusBadge variant="error">{status}</StatusBadge>;
  }
  return <StatusBadge variant="muted">{status}</StatusBadge>;
}
