import { Badge } from "@/components/ui/badge";

type StatusVariant = "active" | "inactive" | "revoked" | "expired" | "success" | "error" | "muted";

const variantClasses: Record<StatusVariant, string> = {
  active: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-300",
  success: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-300",
  inactive: "bg-muted text-muted-foreground border-border",
  muted: "bg-muted text-muted-foreground border-border",
  revoked: "bg-destructive/10 text-destructive border-destructive/20",
  error: "bg-destructive/10 text-destructive border-destructive/20",
  expired: "bg-amber-500/10 text-amber-700 border-amber-500/20 dark:text-amber-300",
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
