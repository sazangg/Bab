import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export type EventDetailRow = { label: string; value: React.ReactNode; mono?: boolean };

/**
 * One side sheet for inspecting a single event/record: a stack of label/value rows plus an
 * optional raw-JSON block. Shared by Activity and Audit (and any future drill-down) so the
 * detail chrome, the Detail row, and the JSON viewer are defined once.
 */
export function EventDetailSheet({
  open,
  onOpenChange,
  title,
  description,
  rows,
  json,
  jsonLabel = "Metadata",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  rows?: EventDetailRow[];
  json?: unknown;
  jsonLabel?: string;
}) {
  const hasBody = (rows && rows.length > 0) || json !== undefined;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description != null ? <SheetDescription>{description}</SheetDescription> : null}
        </SheetHeader>
        {hasBody ? (
          <SheetBody className="flex flex-col gap-5">
            {rows?.map((row) => (
              <div key={row.label} className="flex flex-col gap-1">
                <div className="text-xs font-medium text-muted-foreground">{row.label}</div>
                <div className={row.mono ? "break-all font-mono text-xs" : "text-sm"}>
                  {row.value}
                </div>
              </div>
            ))}
            {json !== undefined ? (
              <div className="flex flex-col gap-1">
                <div className="text-xs font-medium text-muted-foreground">{jsonLabel}</div>
                <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(json, null, 2)}
                </pre>
              </div>
            ) : null}
          </SheetBody>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
