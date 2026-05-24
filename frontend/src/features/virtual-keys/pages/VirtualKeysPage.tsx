import { zodResolver } from "@hookform/resolvers/zod";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { KeyRound, MoreHorizontal, Pencil, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
import { cn } from "@/lib/utils";
import {
  listVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useListProjectsApiV1ProjectsGet,
  useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import type {
  ProjectResponse,
  TeamResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";

type KeySegment = "all" | "active" | "expired" | "revoked";

type KeyRow = {
  key: VirtualKeyResponse;
  project: ProjectResponse;
  team: TeamResponse | undefined;
};

const editKeySchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
});

type EditKeyValues = z.infer<typeof editKeySchema>;

export function VirtualKeysPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<KeySegment>("active");
  const [projectFilter, setProjectFilter] = useState("all");
  const [editingRow, setEditingRow] = useState<KeyRow | null>(null);
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsData = projectsQuery.data?.status === 200 ? projectsQuery.data.data : undefined;
  const teamsData = teamsQuery.data?.status === 200 ? teamsQuery.data.data : undefined;
  const projects = useMemo(() => projectsData ?? [], [projectsData]);
  const teams = useMemo(() => teamsData ?? [], [teamsData]);
  const teamById = useEntityMap(teams);
  const keyQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: ["workspace-virtual-keys", project.id],
      queryFn: () => listVirtualKeysApiV1ProjectsProjectIdKeysGet(project.id),
      enabled: Boolean(project.id),
    })),
  });
  const rows = useMemo<KeyRow[]>(() => {
    return projects.flatMap((project, index) => {
      const response = keyQueries[index]?.data;
      const keys = response?.status === 200 ? response.data : [];
      return keys.map((key) => ({
        key,
        project,
        team: teamById[project.team_id],
      }));
    });
  }, [keyQueries, projects, teamById]);
  const counts = {
    all: rows.length,
    active: rows.filter((row) => getKeyStatus(row.key) === "active").length,
    expired: rows.filter((row) => getKeyStatus(row.key) === "expired").length,
    revoked: rows.filter((row) => getKeyStatus(row.key) === "revoked").length,
  };
  const filtered = rows
    .filter((row) => segment === "all" || getKeyStatus(row.key) === segment)
    .filter((row) => projectFilter === "all" || row.project.id === projectFilter)
    .filter((row) => {
      const term = search.toLowerCase().trim();
      if (!term) return true;
      return `${row.key.name} ${row.key.key_prefix} ${row.project.name} ${row.team?.name ?? ""}`
        .toLowerCase()
        .includes(term);
    });
  const isLoading =
    projectsQuery.isPending || teamsQuery.isPending || keyQueries.some((q) => q.isPending);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Virtual Keys"
        description="Workspace inventory of client-facing keys across all projects."
      />
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading virtual keys...</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title="No virtual keys yet"
          description="Create keys from a project detail page once it has an effective allocation."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All virtual keys</CardTitle>
            <CardDescription>
              {rows.length} total · {counts.active} active · {counts.expired} expired ·{" "}
              {counts.revoked} revoked
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
                  placeholder="Search keys..."
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Select value={projectFilter} onValueChange={setProjectFilter}>
                  <SelectTrigger className="h-9 w-48" aria-label="Filter by project">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All projects</SelectItem>
                    {projects.map((project) => (
                      <SelectItem key={project.id} value={project.id}>
                        {project.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <SegmentControl value={segment} onChange={setSegment} counts={counts} />
              </div>
            </div>
            {filtered.length === 0 ? (
              <EmptyState title="No keys match" description="Try another search or filter." />
            ) : (
              <div className="overflow-hidden rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Prefix</TableHead>
                      <TableHead>Project</TableHead>
                      <TableHead>Team</TableHead>
                      <TableHead>Allocation policy</TableHead>
                      <TableHead>Allowed models</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Updated</TableHead>
                      <TableHead className="w-12">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((row) => (
                      <VirtualKeyRow
                        key={row.key.id}
                        row={row}
                        onOpen={() => navigate(`/projects/${row.project.id}/keys/${row.key.id}`)}
                        onEdit={() => setEditingRow(row)}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      <EditVirtualKeySheet
        row={editingRow}
        onClose={() => setEditingRow(null)}
        onUpdated={async () => {
          setEditingRow(null);
          await queryClient.invalidateQueries();
        }}
      />
    </div>
  );
}

function VirtualKeyRow({
  row,
  onOpen,
  onEdit,
}: {
  row: KeyRow;
  onOpen: () => void;
  onEdit: () => void;
}) {
  const status = getKeyStatus(row.key);
  return (
    <TableRow
      className={cn("cursor-pointer", status !== "active" && "opacity-70")}
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <TableCell className="font-medium">{row.key.name}</TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">
        {row.key.key_prefix}
      </TableCell>
      <TableCell>
        <Link
          to={`/projects/${row.project.id}`}
          onClick={(event) => event.stopPropagation()}
          className="hover:underline"
        >
          {row.project.name}
        </Link>
      </TableCell>
      <TableCell>
        {row.team ? (
          <Link
            to={`/teams/${row.team.id}`}
            onClick={(event) => event.stopPropagation()}
            className="text-muted-foreground hover:text-foreground hover:underline"
          >
            {row.team.name}
          </Link>
        ) : (
          <span className="text-muted-foreground">Unknown team</span>
        )}
      </TableCell>
      <TableCell>
        <StatusBadge variant={row.key.allocation_mode === "custom" ? "expired" : "muted"}>
          {row.key.allocation_mode === "custom" ? "Custom" : "Inherited"}
        </StatusBadge>
      </TableCell>
      <TableCell className="max-w-64 truncate text-muted-foreground">
        {row.key.allowed_models?.join(", ") ?? "All allocation models"}
      </TableCell>
      <TableCell>
        <StatusBadge variant={status === "active" ? "active" : status}>
          {labelStatus(status)}
        </StatusBadge>
      </TableCell>
      <TableCell className="text-muted-foreground" title={formatDateTime(row.key.updated_at)}>
        {formatRelativeFromNow(row.key.updated_at)}
      </TableCell>
      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${row.key.name}`}
              onClick={(event) => event.stopPropagation()}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            onClick={(event) => event.stopPropagation()}
            onCloseAutoFocus={(event) => event.preventDefault()}
          >
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil className="mr-2 size-4" />
              Edit key
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}

function EditVirtualKeySheet({
  row,
  onClose,
  onUpdated,
}: {
  row: KeyRow | null;
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const form = useForm<EditKeyValues>({
    resolver: zodResolver(editKeySchema),
    defaultValues: { name: "" },
  });
  const updateKey = useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Virtual key updated.");
        await onUpdated();
      },
      onError: () => toast.error("Virtual key could not be updated."),
    },
  });

  useEffect(() => {
    if (row) form.reset({ name: row.key.name });
  }, [row, form]);

  const submit = form.handleSubmit((values) => {
    if (!row) return;
    updateKey.mutate({
      projectId: row.project.id,
      keyId: row.key.id,
      data: { name: values.name },
    });
  });

  return (
    <Sheet open={Boolean(row)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit virtual key</SheetTitle>
          <SheetDescription>Rename the client-facing key.</SheetDescription>
        </SheetHeader>
        <form
          id="edit-virtual-key-form"
          className="grid gap-4 overflow-y-auto px-6 py-5"
          onSubmit={submit}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-virtual-key-name">Name</Label>
            <Input id="edit-virtual-key-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
        </form>
        <SheetFooter>
          <Button type="submit" form="edit-virtual-key-form" disabled={updateKey.isPending}>
            {updateKey.isPending ? "Saving..." : "Save changes"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function SegmentControl({
  value,
  onChange,
  counts,
}: {
  value: KeySegment;
  onChange: (value: KeySegment) => void;
  counts: Record<KeySegment, number>;
}) {
  return (
    <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
      {(["all", "active", "expired", "revoked"] as const).map((item) => (
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

function useEntityMap<T extends { id: string }>(items: T[]) {
  return useMemo(() => {
    const map: Record<string, T> = {};
    for (const item of items) map[item.id] = item;
    return map;
  }, [items]);
}

function getKeyStatus(key: VirtualKeyResponse): Exclude<KeySegment, "all"> {
  if (key.revoked_at) return "revoked";
  if (key.expires_at && new Date(key.expires_at) < new Date()) return "expired";
  return "active";
}

function labelStatus(status: Exclude<KeySegment, "all">) {
  return status[0].toUpperCase() + status.slice(1);
}
