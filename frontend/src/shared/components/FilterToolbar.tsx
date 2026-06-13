import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type FilterChip = {
  key: string;
  label: React.ReactNode;
  onRemove: () => void;
};

/**
 * Toolbar wrapper for filter controls plus a row of active-filter chips. Gives every
 * heavily-filtered screen (usage, activity, audit, guardrails) a consistent layout and
 * a clear, removable summary of what's currently applied.
 */
export function FilterToolbar({
  children,
  chips,
  onClearAll,
  className,
}: {
  children: React.ReactNode;
  chips?: FilterChip[];
  onClearAll?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      {chips && chips.length > 0 ? <FilterChips chips={chips} onClearAll={onClearAll} /> : null}
    </div>
  );
}

export function FilterChips({
  chips,
  onClearAll,
}: {
  chips: FilterChip[];
  onClearAll?: () => void;
}) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 py-0.5 pl-2.5 pr-1 text-xs text-foreground"
        >
          {chip.label}
          <button
            type="button"
            onClick={chip.onRemove}
            aria-label="Remove filter"
            className="flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      {onClearAll ? (
        <Button variant="ghost" size="xs" onClick={onClearAll}>
          Clear all
        </Button>
      ) : null}
    </div>
  );
}
