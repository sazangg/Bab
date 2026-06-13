import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";

export type DataTableColumn<T> = {
  key: string;
  header: React.ReactNode;
  cell?: (row: T) => React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  headClassName?: string;
};

type DataTableEmpty = {
  icon?: LucideIcon;
  title?: string;
  description?: string;
  action?: React.ReactNode;
};

/**
 * A table with loading (skeleton), empty, and error states built in, plus an optional
 * footer (e.g. pagination) and row click. Replaces the per-table state reimplementations
 * scattered across the app — pass `columns` + `data` and the states are handled.
 */
export function DataTable<T>({
  columns,
  data,
  loading = false,
  error,
  onRetry,
  getRowKey,
  onRowClick,
  rowClassName,
  empty,
  skeletonRows = 6,
  footer,
  className,
}: {
  columns: DataTableColumn<T>[];
  data: T[];
  loading?: boolean;
  error?: string | boolean;
  onRetry?: () => void;
  getRowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T, index: number) => string | undefined;
  empty?: DataTableEmpty;
  skeletonRows?: number;
  footer?: React.ReactNode;
  className?: string;
}) {
  const colCount = columns.length;
  const alignClass = (align?: DataTableColumn<T>["align"]) =>
    align === "right" ? "text-right" : align === "center" ? "text-center" : "";

  return (
    <div className={cn("overflow-hidden rounded-md border border-border", className)}>
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                className={cn(alignClass(column.align), column.headClassName)}
              >
                {column.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: skeletonRows }).map((_, rowIndex) => (
              <TableRow key={`skeleton-${rowIndex}`}>
                {columns.map((column) => (
                  <TableCell key={column.key} className={alignClass(column.align)}>
                    <Skeleton className="h-4 w-full max-w-36" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : error ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={colCount} className="h-32">
                <div className="flex flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
                  <span>{typeof error === "string" ? error : "Could not load data."}</span>
                  {onRetry ? (
                    <Button variant="outline" size="sm" onClick={onRetry}>
                      Retry
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ) : data.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={colCount} className="p-0">
                <EmptyState
                  icon={empty?.icon}
                  title={empty?.title ?? "Nothing here yet"}
                  description={empty?.description}
                  action={empty?.action}
                />
              </TableCell>
            </TableRow>
          ) : (
            data.map((row, rowIndex) => {
              const clickable = Boolean(onRowClick);
              return (
                <TableRow
                  key={getRowKey(row, rowIndex)}
                  className={cn(clickable && "cursor-pointer", rowClassName?.(row, rowIndex))}
                  tabIndex={clickable ? 0 : undefined}
                  onClick={clickable ? () => onRowClick?.(row) : undefined}
                  onKeyDown={
                    clickable
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onRowClick?.(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((column) => (
                    <TableCell
                      key={column.key}
                      className={cn(alignClass(column.align), column.className)}
                    >
                      {column.cell
                        ? column.cell(row)
                        : String((row as Record<string, unknown>)[column.key] ?? "")}
                    </TableCell>
                  ))}
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
      {footer ? (
        <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs text-muted-foreground">
          {footer}
        </div>
      ) : null}
    </div>
  );
}
