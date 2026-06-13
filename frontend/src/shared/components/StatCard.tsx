import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * The single stat tile for the app. Replaces the divergent `Fact` / `MetricCard` /
 * `Stat` / `ImpactCount` implementations: a label, a prominent value, an optional hint
 * line, and an optional icon chip.
 */
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <Card size="sm" className={cn("h-full", className)}>
      <CardContent className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="text-caption text-muted-foreground">{label}</div>
          <div className="text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
          {hint != null && <div className="text-xs text-muted-foreground">{hint}</div>}
        </div>
        {Icon ? (
          <div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/40 text-muted-foreground">
            <Icon className="size-4" />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
