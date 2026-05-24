import { useQueryClient } from "@tanstack/react-query";
import { Layers3, MoreHorizontal, Pencil, Power, Search, Star } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  useListAllocationsApiV1ProjectsAllocationsGet,
  useListProjectsApiV1ProjectsGet,
  useUpdateAllocationApiV1ProjectsAllocationsAllocationIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import type {
  AllocationResponse,
  ProjectResponse,
  TeamResponse,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";

type AllocationSegment = "all" | "active" | "inactive";
type TargetFilter = "all" | "team" | "project";
type AllocationEditPayload = {
  name: string;
  description: string | null;
  is_default: boolean;
  is_active: boolean;
  budget_cents: number | null;
  max_requests: number | null;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  max_tokens_per_request: number | null;
  window: string;
};

export function AllocationsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<AllocationSegment>("active");
  const [targetFilter, setTargetFilter] = useState<TargetFilter>("all");
  const [editingAllocation, setEditingAllocation] = useState<AllocationResponse | null>(null);
  const updateAllocation = useUpdateAllocationApiV1ProjectsAllocationsAllocationIdPatch({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries();
        toast.success("Allocation updated");
      },
      onError: () => toast.error("Allocation could not be updated"),
    },
  });
  const allocationsQuery = useListAllocationsApiV1ProjectsAllocationsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const allocations = allocationsQuery.data?.status === 200 ? allocationsQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamById = useEntityMap(teams);
  const projectById = useEntityMap(projects);

  const counts = {
    all: allocations.length,
    active: allocations.filter((allocation) => allocation.is_active).length,
    inactive: allocations.filter((allocation) => !allocation.is_active).length,
  };
  const filtered = allocations
    .filter((allocation) => {
      if (segment === "active") return allocation.is_active;
      if (segment === "inactive") return !allocation.is_active;
      return true;
    })
    .filter((allocation) => targetFilter === "all" || allocation.target_type === targetFilter)
    .filter((allocation) => {
      const term = search.toLowerCase().trim();
      if (!term) return true;
      const projectName = allocation.project_id ? projectById[allocation.project_id]?.name : "";
      const teamName = allocation.team_id ? teamById[allocation.team_id]?.name : "";
      return `${allocation.name} ${allocation.description ?? ""} ${projectName} ${teamName}`
        .toLowerCase()
        .includes(term);
    });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Allocations"
        description="Workspace inventory of team and project allocation policies."
      />
      {allocationsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading allocations...</p>
      ) : allocations.length === 0 ? (
        <EmptyState
          icon={Layers3}
          title="No allocations yet"
          description="Create allocations from a team or project detail page."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All allocations</CardTitle>
            <CardDescription>
              {allocations.length} total · {counts.active} active · {counts.inactive} inactive
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative max-w-md flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search allocations..."
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={targetFilter}
                  onValueChange={(value) => setTargetFilter(value as TargetFilter)}
                >
                  <SelectTrigger className="h-9 w-40" aria-label="Filter by target">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All targets</SelectItem>
                    <SelectItem value="team">Teams</SelectItem>
                    <SelectItem value="project">Projects</SelectItem>
                  </SelectContent>
                </Select>
                <SegmentControl value={segment} onChange={setSegment} counts={counts} />
              </div>
            </div>
            {filtered.length === 0 ? (
              <EmptyState
                title="No allocations match"
                description="Try another search or filter."
              />
            ) : (
              <div className="overflow-hidden rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Target</TableHead>
                      <TableHead>Models</TableHead>
                      <TableHead>Budget</TableHead>
                      <TableHead>Requests</TableHead>
                      <TableHead>Window</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Updated</TableHead>
                      <TableHead className="w-12">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((allocation) => (
                      <AllocationRow
                        key={allocation.id}
                        allocation={allocation}
                        team={allocation.team_id ? teamById[allocation.team_id] : undefined}
                        project={
                          allocation.project_id ? projectById[allocation.project_id] : undefined
                        }
                        onOpen={() => {
                          if (allocation.project_id) navigate(`/projects/${allocation.project_id}`);
                          else if (allocation.team_id) navigate(`/teams/${allocation.team_id}`);
                        }}
                        onEdit={() => setEditingAllocation(allocation)}
                        onPatch={(patch) =>
                          updateAllocation.mutate({
                            allocationId: allocation.id,
                            data: patch,
                          })
                        }
                        isUpdating={updateAllocation.isPending}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      <GlobalAllocationEditSheet
        allocation={editingAllocation}
        open={Boolean(editingAllocation)}
        onOpenChange={(open) => !open && setEditingAllocation(null)}
        isPending={updateAllocation.isPending}
        onSubmit={(allocationId, data) =>
          updateAllocation.mutate(
            { allocationId, data },
            { onSuccess: () => setEditingAllocation(null) },
          )
        }
      />
    </div>
  );
}

function AllocationRow({
  allocation,
  team,
  project,
  onOpen,
  onEdit,
  onPatch,
  isUpdating,
}: {
  allocation: AllocationResponse;
  team: TeamResponse | undefined;
  project: ProjectResponse | undefined;
  onOpen: () => void;
  onEdit: () => void;
  onPatch: (patch: { is_active?: boolean; is_default?: boolean }) => void;
  isUpdating: boolean;
}) {
  const targetLabel = project?.name ?? team?.name ?? "Unknown target";
  const targetHref = project ? `/projects/${project.id}` : team ? `/teams/${team.id}` : undefined;

  return (
    <TableRow
      className={cn("cursor-pointer", !allocation.is_active && "opacity-60")}
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <TableCell>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-medium">{allocation.name}</span>
          <span className="max-w-md truncate text-xs text-muted-foreground">
            {allocation.description || "No description"}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1">
          <span className="text-xs capitalize text-muted-foreground">{allocation.target_type}</span>
          {targetHref ? (
            <Link
              to={targetHref}
              onClick={(event) => event.stopPropagation()}
              className="font-medium hover:underline"
            >
              {targetLabel}
            </Link>
          ) : (
            <span className="font-medium">{targetLabel}</span>
          )}
        </div>
      </TableCell>
      <TableCell className="tabular-nums text-muted-foreground">
        {allocation.offerings.length}
      </TableCell>
      <TableCell className="text-muted-foreground">
        {formatCents(allocation.budget_cents)}
      </TableCell>
      <TableCell className="text-muted-foreground">
        {allocation.max_requests?.toLocaleString() ?? "No cap"}
      </TableCell>
      <TableCell className="capitalize text-muted-foreground">{allocation.window}</TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {allocation.is_default ? <StatusBadge variant="active">Default</StatusBadge> : null}
          <StatusBadge variant={allocation.is_active ? "active" : "inactive"}>
            {allocation.is_active ? "Active" : "Inactive"}
          </StatusBadge>
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground" title={formatDateTime(allocation.updated_at)}>
        {formatRelativeFromNow(allocation.updated_at)}
      </TableCell>
      <TableCell onClick={(event) => event.stopPropagation()}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={isUpdating}
              aria-label={`Actions for ${allocation.name}`}
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil className="size-4" />
              Edit allocation
            </DropdownMenuItem>
            {!allocation.is_default ? (
              <DropdownMenuItem onSelect={() => onPatch({ is_default: true })}>
                <Star className="size-4" />
                Make default
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onPatch({ is_active: !allocation.is_active })}>
              <Power className="size-4" />
              {allocation.is_active ? "Deactivate" : "Activate"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}

function SegmentControl({
  value,
  onChange,
  counts,
}: {
  value: AllocationSegment;
  onChange: (value: AllocationSegment) => void;
  counts: Record<AllocationSegment, number>;
}) {
  return (
    <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
      {(["all", "active", "inactive"] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onChange(item)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
            value === item
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {item}
          <span className="ml-1.5 text-muted-foreground">{counts[item]}</span>
        </button>
      ))}
    </div>
  );
}

function GlobalAllocationEditSheet({
  allocation,
  open,
  onOpenChange,
  isPending,
  onSubmit,
}: {
  allocation: AllocationResponse | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isPending: boolean;
  onSubmit: (allocationId: string, data: AllocationEditPayload) => void;
}) {
  if (!allocation) {
    return <Sheet open={open} onOpenChange={onOpenChange} />;
  }

  return (
    <GlobalAllocationEditSheetContent
      key={allocation.id}
      allocation={allocation}
      open={open}
      onOpenChange={onOpenChange}
      isPending={isPending}
      onSubmit={onSubmit}
    />
  );
}

function GlobalAllocationEditSheetContent({
  allocation,
  open,
  onOpenChange,
  isPending,
  onSubmit,
}: {
  allocation: AllocationResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isPending: boolean;
  onSubmit: (allocationId: string, data: AllocationEditPayload) => void;
}) {
  const [values, setValues] = useState({
    name: allocation.name,
    description: allocation.description ?? "",
    is_default: allocation.is_default,
    is_active: allocation.is_active,
    budget_dollars: allocation.budget_cents == null ? "" : String(allocation.budget_cents / 100),
    max_requests: allocation.max_requests?.toString() ?? "",
    max_input_tokens: allocation.max_input_tokens?.toString() ?? "",
    max_output_tokens: allocation.max_output_tokens?.toString() ?? "",
    max_tokens_per_request: allocation.max_tokens_per_request?.toString() ?? "",
    window: allocation.window,
  });

  const updateValue = (field: keyof typeof values, value: string | boolean) =>
    setValues((current) => ({ ...current, [field]: value }));

  const submit = () => {
    if (!allocation || !values.name.trim()) return;
    onSubmit(allocation.id, {
      name: values.name.trim(),
      description: values.description.trim() || null,
      is_default: values.is_default,
      is_active: values.is_active,
      budget_cents: toCents(values.budget_dollars),
      max_requests: toOptionalInt(values.max_requests),
      max_input_tokens: toOptionalInt(values.max_input_tokens),
      max_output_tokens: toOptionalInt(values.max_output_tokens),
      max_tokens_per_request: toOptionalInt(values.max_tokens_per_request),
      window: values.window,
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit allocation</SheetTitle>
          <SheetDescription>
            Update allocation metadata, state, and limits from the global inventory.
          </SheetDescription>
        </SheetHeader>
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <section className="rounded-md border p-4">
            <div className="mb-4">
              <h3 className="text-sm font-medium">Basics</h3>
              <p className="text-xs text-muted-foreground">
                Routing access is edited from the owning team or project page.
              </p>
            </div>
            <div className="grid gap-3">
              <Field label="Name" htmlFor="global-allocation-name">
                <Input
                  id="global-allocation-name"
                  value={values.name}
                  onChange={(event) => updateValue("name", event.target.value)}
                />
              </Field>
              <Field label="Description" htmlFor="global-allocation-description">
                <Textarea
                  id="global-allocation-description"
                  className="min-h-24"
                  value={values.description}
                  onChange={(event) => updateValue("description", event.target.value)}
                />
              </Field>
            </div>
          </section>

          <section className="rounded-md border p-4">
            <div className="mb-4">
              <h3 className="text-sm font-medium">State</h3>
              <p className="text-xs text-muted-foreground">
                Defaults are inherited by virtual keys unless they use a custom allocation.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <SwitchRow
                label="Default allocation"
                description="Use as the default for its target."
                checked={values.is_default}
                onCheckedChange={(checked) => updateValue("is_default", checked)}
              />
              <SwitchRow
                label="Active"
                description="Inactive allocations cannot route requests."
                checked={values.is_active}
                onCheckedChange={(checked) => updateValue("is_active", checked)}
              />
            </div>
          </section>

          <section className="rounded-md border p-4">
            <div className="mb-4">
              <h3 className="text-sm font-medium">Limits</h3>
              <p className="text-xs text-muted-foreground">
                Blank values mean this allocation does not enforce that cap.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Budget ($)" htmlFor="global-allocation-budget">
                <Input
                  id="global-allocation-budget"
                  type="number"
                  step="0.01"
                  value={values.budget_dollars}
                  onChange={(event) => updateValue("budget_dollars", event.target.value)}
                />
              </Field>
              <Field label="Window">
                <Select
                  value={values.window}
                  onValueChange={(value) => updateValue("window", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="daily">Daily</SelectItem>
                    <SelectItem value="weekly">Weekly</SelectItem>
                    <SelectItem value="monthly">Monthly</SelectItem>
                    <SelectItem value="lifetime">Lifetime</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <NumberField
                label="Max requests"
                value={values.max_requests}
                onChange={(value) => updateValue("max_requests", value)}
              />
              <NumberField
                label="Max tokens/request"
                value={values.max_tokens_per_request}
                onChange={(value) => updateValue("max_tokens_per_request", value)}
              />
              <NumberField
                label="Input tokens"
                value={values.max_input_tokens}
                onChange={(value) => updateValue("max_input_tokens", value)}
              />
              <NumberField
                label="Output tokens"
                value={values.max_output_tokens}
                onChange={(value) => updateValue("max_output_tokens", value)}
              />
            </div>
          </section>
        </div>
        <SheetFooter>
          <Button disabled={isPending || !values.name.trim()} onClick={submit}>
            {isPending ? "Saving..." : "Save allocation"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <Input type="number" value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

function SwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/20 p-3">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

function toOptionalInt(value: string) {
  const trimmed = value.trim();
  return trimmed ? Number.parseInt(trimmed, 10) : null;
}

function toCents(value: string) {
  const trimmed = value.trim();
  return trimmed ? Math.round(Number.parseFloat(trimmed) * 100) : null;
}

function useEntityMap<T extends { id: string }>(items: T[]) {
  return useMemo(() => {
    const map: Record<string, T> = {};
    for (const item of items) map[item.id] = item;
    return map;
  }, [items]);
}

function formatCents(value: number | null | undefined) {
  return value == null ? "No cap" : `$${(value / 100).toLocaleString()}`;
}
