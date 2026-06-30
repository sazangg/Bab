import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Building2, MoreHorizontal, Pencil, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { ResourceListPage, type ResourceSegment } from "@/shared/templates/ResourceListPage";
import { hasPermission, isTeamAdmin } from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import {
  useCreateTeamApiV1TeamsPost,
  useListTeamsApiV1TeamsGet,
  useUpdateTeamApiV1TeamsTeamIdPatch,
} from "@/shared/api/generated/teams/teams";
import type { TeamResponse } from "@/shared/api/generated/schemas";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";
import { slugify } from "@/features/teams/lib/slug";

const teamSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  slug: z
    .string()
    .max(100)
    .regex(/^[a-z0-9-]*$/, "Use lowercase letters, numbers, and dashes only")
    .optional(),
  description: z.string().max(1000).optional(),
});

type TeamFormValues = z.infer<typeof teamSchema>;

export function TeamsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editingTeam, setEditingTeam] = useState<TeamResponse | null>(null);
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<ResourceSegment>("active");

  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canCreateTeam = hasPermission(currentUser, "teams.manage");
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projectsData = projectsQuery.data?.status === 200 ? projectsQuery.data.data : undefined;
  const projectCountByTeam = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const project of projectsData ?? []) {
      counts[project.team_id] = (counts[project.team_id] ?? 0) + 1;
    }
    return counts;
  }, [projectsData]);
  const canEditTeam = (team: TeamResponse) =>
    hasPermission(currentUser, "teams.manage") || isTeamAdmin(currentUser, team.id);

  const columns: DataTableColumn<TeamResponse>[] = [
    {
      key: "name",
      header: "Name",
      className: "font-medium",
      cell: (team) => (
        <Link
          to={`/teams/${team.id}`}
          onClick={(event) => event.stopPropagation()}
          className="hover:underline"
        >
          {team.name}
        </Link>
      ),
    },
    {
      key: "slug",
      header: "Slug",
      className: "font-mono text-xs text-muted-foreground",
      cell: (team) => team.slug,
    },
    {
      key: "projects",
      header: "Projects",
      align: "right",
      className: "tabular-nums text-muted-foreground",
      cell: (team) => projectCountByTeam[team.id] ?? 0,
    },
    {
      key: "description",
      header: "Description",
      className: "max-w-md truncate text-muted-foreground",
      cell: (team) => team.description || "—",
    },
    {
      key: "status",
      header: "Status",
      cell: (team) => (
        <StatusBadge variant={team.is_active ? "active" : "inactive"}>
          {team.is_active ? "Active" : "Archived"}
        </StatusBadge>
      ),
    },
    {
      key: "updated",
      header: "Updated",
      className: "text-muted-foreground",
      cell: (team) => (
        <span title={formatDateTime(team.updated_at)}>
          {formatRelativeFromNow(team.updated_at)}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      headClassName: "w-[1%]",
      cell: (team) =>
        canEditTeam(team) ? (
          <div onClick={(event) => event.stopPropagation()}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Team actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditingTeam(team)}>
                  <Pencil data-icon="inline-start" />
                  Edit team
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null,
    },
  ];

  return (
    <ResourceListPage
      title="Teams"
      description="Teams group projects under a business, product, or division boundary."
      headerActions={
        canCreateTeam ? (
          <CreateTeamSheet
            open={createOpen}
            onOpenChange={setCreateOpen}
            onCreated={async (team) => {
              await queryClient.invalidateQueries();
              setCreateOpen(false);
              toast.success(`Team "${team.name}" created.`);
              navigate(`/teams/${team.id}`);
            }}
          />
        ) : null
      }
      items={teams}
      isLoading={teamsQuery.isPending}
      getIsActive={(team) => team.is_active}
      getRowKey={(team) => team.id}
      noun="team"
      loadingLabel="Loading teams..."
      emptyIcon={Building2}
      emptyTitle="No teams yet"
      emptyDescription="Create the first team to start organizing projects."
      emptyAction={
        canCreateTeam ? (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus />
            New team
          </Button>
        ) : undefined
      }
      cardTitle="All teams"
      search={search}
      onSearchChange={setSearch}
      searchPlaceholder="Search teams..."
      matchesSearch={(team, term) =>
        `${team.name} ${team.slug} ${team.description ?? ""}`.toLowerCase().includes(term)
      }
      segment={segment}
      onSegmentChange={setSegment}
      columns={columns}
      renderCard={(team) => (
        <TeamCard
          team={team}
          projectCount={projectCountByTeam[team.id] ?? 0}
          onOpen={() => navigate(`/teams/${team.id}`)}
          onEdit={() => setEditingTeam(team)}
          canEdit={canEditTeam(team)}
        />
      )}
      onRowClick={(team) => navigate(`/teams/${team.id}`)}
      rowClassName={(team) => (!team.is_active ? "opacity-60" : undefined)}
      noMatchTitle="No teams match"
      noMatchDescription="Try a different search or status."
      onClearFilters={() => {
        setSearch("");
        setSegment("active");
      }}
      editSheet={
        <EditTeamSheet
          team={editingTeam}
          onClose={() => setEditingTeam(null)}
          onUpdated={async () => {
            setEditingTeam(null);
            await queryClient.invalidateQueries();
            toast.success("Team updated.");
          }}
        />
      }
    />
  );
}

function TeamCard({
  team,
  projectCount,
  onOpen,
  onEdit,
  canEdit,
}: {
  team: TeamResponse;
  projectCount: number;
  onOpen: () => void;
  onEdit: () => void;
  canEdit: boolean;
}) {
  return (
    <div
      role="button"
      aria-label={`Open team ${team.name}`}
      tabIndex={0}
      className={cn(
        "rounded-lg border bg-card p-4 shadow-sm transition-colors hover:bg-muted/30",
        !team.is_active && "opacity-70",
      )}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/teams/${team.id}`}
            onClick={(event) => event.stopPropagation()}
            className="font-medium underline-offset-4 hover:underline"
          >
            {team.name}
          </Link>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{team.slug}</p>
          <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
            {team.description || "No description."}
          </p>
        </div>
        {canEdit ? (
          <div onClick={(event) => event.stopPropagation()}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Team actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={onEdit}>
                  <Pencil data-icon="inline-start" />
                  Edit team
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <StatusBadge variant={team.is_active ? "active" : "inactive"}>
          {team.is_active ? "Active" : "Archived"}
        </StatusBadge>
        <span>{projectCount} projects</span>
        <span title={formatDateTime(team.updated_at)}>
          Updated {formatRelativeFromNow(team.updated_at)}
        </span>
      </div>
    </div>
  );
}

function EditTeamSheet({
  team,
  onClose,
  onUpdated,
}: {
  team: TeamResponse | null;
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const form = useForm<TeamFormValues>({
    resolver: zodResolver(teamSchema),
    defaultValues: { name: "", slug: "", description: "" },
  });
  const updateTeam = useUpdateTeamApiV1TeamsTeamIdPatch({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          await onUpdated();
        }
      },
      onError: () => toast.error("Team could not be updated."),
    },
  });

  useEffect(() => {
    if (!team) return;
    form.reset({
      name: team.name,
      slug: team.slug,
      description: team.description ?? "",
    });
  }, [team, form]);

  const submit = form.handleSubmit((values) => {
    if (!team) return;
    updateTeam.mutate({
      teamId: team.id,
      data: {
        name: values.name,
        slug: values.slug?.trim() ? values.slug : undefined,
        description: values.description?.trim() ? values.description : null,
        is_active: team.is_active,
      },
    });
  });

  return (
    <Sheet open={Boolean(team)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit team</SheetTitle>
          <SheetDescription>Rename or update this team.</SheetDescription>
        </SheetHeader>
        <form
          id="edit-team-form"
          className="grid gap-4 overflow-y-auto px-6 py-5"
          onSubmit={submit}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-team-name">Name</Label>
            <Input id="edit-team-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-team-slug">Slug</Label>
            <Input id="edit-team-slug" {...form.register("slug")} />
            <p className="text-xs text-muted-foreground">Used in URLs and attribution.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-team-description">Description</Label>
            <Textarea id="edit-team-description" rows={4} {...form.register("description")} />
          </div>
        </form>
        <SheetFooter>
          <Button type="submit" form="edit-team-form" disabled={updateTeam.isPending}>
            {updateTeam.isPending ? "Saving..." : "Save changes"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CreateTeamSheet({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (team: TeamResponse) => Promise<void>;
}) {
  const form = useForm<TeamFormValues>({
    resolver: zodResolver(teamSchema),
    defaultValues: { name: "", slug: "", description: "" },
  });
  const watchedName = useWatch({ control: form.control, name: "name" });
  const watchedSlug = useWatch({ control: form.control, name: "slug" });
  const slugPreview = watchedSlug?.trim()
    ? slugify(watchedSlug)
    : watchedName?.trim()
      ? slugify(watchedName)
      : "";

  const createTeam = useCreateTeamApiV1TeamsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          form.reset();
          await onCreated(response.data);
        }
      },
      onError: (error) => {
        if (isAxiosError(error) && error.response?.status === 409) {
          form.setError("slug", {
            type: "server",
            message: "A team with this slug already exists.",
          });
          toast.error("Slug already in use. Pick another.");
          return;
        }
        toast.error("Team could not be created. Try again.");
      },
    },
  });

  const submit = form.handleSubmit((values) =>
    createTeam.mutate({
      data: {
        name: values.name,
        slug: values.slug?.trim() ? values.slug : null,
        description: values.description?.trim() ? values.description : null,
      },
    }),
  );

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) form.reset();
      }}
    >
      <SheetTrigger asChild>
        <Button>
          <Plus />
          New team
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>New team</SheetTitle>
          <SheetDescription>Create a team that will own one or more projects.</SheetDescription>
        </SheetHeader>
        <form
          id="create-team-form"
          className="grid gap-4 overflow-y-auto px-6 py-5"
          onSubmit={submit}
        >
          <div className="space-y-1.5">
            <Label htmlFor="team-name">Name</Label>
            <Input id="team-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="team-slug">Slug</Label>
            <Input
              id="team-slug"
              placeholder="Leave blank to auto-generate"
              {...form.register("slug")}
            />
            {form.formState.errors.slug ? (
              <p className="text-xs text-destructive">{form.formState.errors.slug.message}</p>
            ) : slugPreview ? (
              <p className="text-xs text-muted-foreground">
                Will be created as <span className="font-mono text-foreground">{slugPreview}</span>
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Leave blank to generate from the name.
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="team-description">Description</Label>
            <Textarea id="team-description" rows={4} {...form.register("description")} />
            {form.formState.errors.description ? (
              <p className="text-xs text-destructive">
                {form.formState.errors.description.message}
              </p>
            ) : null}
          </div>
        </form>
        <SheetFooter>
          <Button type="submit" form="create-team-form" disabled={createTeam.isPending}>
            {createTeam.isPending ? "Creating..." : "Create team"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
