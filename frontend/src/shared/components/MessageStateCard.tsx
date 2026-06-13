import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Tone = "default" | "destructive";

/**
 * Centered icon + title + description + action card. One component for the
 * forbidden / no-access / error / coming-soon states that are currently near-identical
 * one-off cards across the app.
 */
export function MessageStateCard({
  icon: Icon,
  title,
  description,
  action,
  tone = "default",
  fillViewport = true,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  tone?: Tone;
  fillViewport?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex w-full items-center justify-center p-6",
        fillViewport && "min-h-[60vh]",
        className,
      )}
    >
      <Card className="w-full max-w-md">
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          {Icon ? (
            <div
              className={cn(
                "flex size-12 items-center justify-center rounded-full",
                tone === "destructive"
                  ? "bg-destructive/10 text-destructive"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <Icon className="size-6" />
            </div>
          ) : null}
          <div className="space-y-1">
            <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
            {description != null && (
              <p className="text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {action ? <div className="pt-1">{action}</div> : null}
        </CardContent>
      </Card>
    </div>
  );
}
