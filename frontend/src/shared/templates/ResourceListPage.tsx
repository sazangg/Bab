import { Search, type LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

export type ResourceSegment = "all" | "active" | "archived";

const SEGMENTS: ResourceSegment[] = ["all", "active", "archived"];

/**
 * The list-page shell shared by Teams and Projects: page header (+ create action), a
 * loading state, a no-items empty state, and a Card with a count summary, a search box, an
 * all/active/archived segment toggle (plus an optional extra filter), a no-match empty
 * state, and a responsive body that renders cards on mobile and a DataTable on desktop.
 *
 * The caller supplies the data, the item accessors, the DataTable columns, the mobile card
 * renderer, and the create/edit sheets; segment + search filtering happen here.
 */
export function ResourceListPage<T>({
  title,
  description,
  headerActions,
  items,
  isLoading,
  getIsActive,
  getRowKey,
  noun,
  loadingLabel,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  emptyAction,
  cardTitle,
  search,
  onSearchChange,
  searchPlaceholder,
  matchesSearch,
  segment,
  onSegmentChange,
  extraFilter,
  toolbarExtra,
  columns,
  renderCard,
  onRowClick,
  rowClassName,
  noMatchTitle = "No matches",
  noMatchDescription,
  editSheet,
}: {
  title: string;
  description: string;
  headerActions?: React.ReactNode;
  items: T[];
  isLoading: boolean;
  getIsActive: (item: T) => boolean;
  getRowKey: (item: T) => string;
  noun: string;
  loadingLabel: string;
  emptyIcon?: LucideIcon;
  emptyTitle: string;
  emptyDescription: string;
  emptyAction?: React.ReactNode;
  cardTitle: string;
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  matchesSearch: (item: T, term: string) => boolean;
  segment: ResourceSegment;
  onSegmentChange: (segment: ResourceSegment) => void;
  extraFilter?: (item: T) => boolean;
  toolbarExtra?: React.ReactNode;
  columns: DataTableColumn<T>[];
  renderCard: (item: T) => React.ReactNode;
  onRowClick?: (item: T) => void;
  rowClassName?: (item: T) => string | undefined;
  noMatchTitle?: string;
  noMatchDescription: string;
  editSheet?: React.ReactNode;
}) {
  const isMobile = useIsMobile();
  const counts: Record<ResourceSegment, number> = {
    all: items.length,
    active: items.filter(getIsActive).length,
    archived: items.filter((item) => !getIsActive(item)).length,
  };
  const term = search.toLowerCase().trim();
  const filtered = items
    .filter((item) =>
      segment === "active" ? getIsActive(item) : segment === "archived" ? !getIsActive(item) : true,
    )
    .filter((item) => !extraFilter || extraFilter(item))
    .filter((item) => !term || matchesSearch(item, term));

  return (
    <>
      <PageHeader title={title} description={description} actions={headerActions} />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">{loadingLabel}</p>
      ) : items.length === 0 ? (
        <EmptyState
          icon={emptyIcon}
          title={emptyTitle}
          description={emptyDescription}
          action={emptyAction}
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{cardTitle}</CardTitle>
            <CardDescription>
              {counts.all} {counts.all === 1 ? noun : `${noun}s`} · {counts.active} active ·{" "}
              {counts.archived} archived
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative max-w-md flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={search}
                  onChange={(event) => onSearchChange(event.target.value)}
                  placeholder={searchPlaceholder}
                />
              </div>
              <div className="flex items-center gap-2">
                {toolbarExtra}
                <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
                  {SEGMENTS.map((value) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => onSegmentChange(value)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                        segment === value
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {value}
                      <span className="ml-1.5 text-muted-foreground">{counts[value]}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {filtered.length === 0 ? (
              <div className="rounded-md border border-dashed p-8 text-center">
                <p className="text-sm font-medium">{noMatchTitle}</p>
                <p className="mt-1 text-sm text-muted-foreground">{noMatchDescription}</p>
              </div>
            ) : isMobile ? (
              <div className="grid gap-3">
                {filtered.map((item) => (
                  <div key={getRowKey(item)}>{renderCard(item)}</div>
                ))}
              </div>
            ) : (
              <DataTable
                columns={columns}
                data={filtered}
                getRowKey={getRowKey}
                onRowClick={onRowClick}
                rowClassName={rowClassName}
              />
            )}
          </CardContent>
        </Card>
      )}
      {editSheet}
    </>
  );
}
