import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, FolderKanban, MoreHorizontal, Pencil, Plus } from "lucide-react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import {
  hasAnyTeamAdminMembership,
  hasPermission,
  isProjectAdmin,
  isTeamAdmin,
  canViewTeam,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { getProblemDetail } from "@/shared/api/problem-detail";

import {
  useListProjectsApiV1ProjectsGet,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
import {
  useCreateTeamProjectApiV1TeamsTeamIdProjectsPost,
  useListTeamsApiV1TeamsGet,
} from "@/shared/api/generated/teams/teams";
import type { ProjectResponse, TeamResponse } from "@/shared/api/generated/schemas";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";

const newProjectSchema = z.object({
  teamId: z.string().min(1, "Pick a team"),
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional(),
});

type NewProjectValues = z.infer<typeof newProjectSchema>;

export function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamsData = teamsQuery.data?.status === 200 ? teamsQuery.data.data : undefined;
  const teams = useMemo(() => teamsData ?? [], [teamsData]);
  const canManageAllProjects = hasPermission(currentUser, "projects.manage");
  const canCreateProject = canManageAllProjects || hasAnyTeamAdminMembership(currentUser);
  const activeTeams = useMemo(
    () =>
      teams.filter(
        (team) => team.is_active && (canManageAllProjects || isTeamAdmin(currentUser, team.id)),
      ),
    [canManageAllProjects, currentUser, teams],
  );
  const teamById = useMemo(() => {
    const map: Record<string, TeamResponse> = {};
    for (const team of teams) {
      map[team.id] = team;
    }
    return map;
  }, [teams]);

  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<ResourceSegment>("active");
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [newOpen, setNewOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectResponse | null>(null);

  const canCreate = canCreateProject && activeTeams.length > 0;
  const canManageProject = (project: ProjectResponse) =>
    canManageAllProjects ||
    isTeamAdmin(currentUser, project.team_id) ||
    isProjectAdmin(currentUser, project.id);
  const teamFor = (project: ProjectResponse) =>
    teamById[project.team_id] ??
    (project.team_name ? { id: project.team_id, name: project.team_name } : undefined);

  const columns: DataTableColumn<ProjectResponse>[] = [
    {
      key: "name",
      header: "Name",
      className: "font-medium",
      cell: (project) => (
        <Link
          to={`/projects/${project.id}`}
          onClick={(event) => event.stopPropagation()}
          className="hover:underline"
        >
          {project.name}
        </Link>
      ),
    },
    {
      key: "team",
      header: "Team",
      cell: (project) => {
        const team = teamFor(project);
        if (team && canViewTeam(currentUser, project.team_id)) {
          return (
            <Link
              to={`/teams/${team.id}`}
              onClick={(event) => event.stopPropagation()}
              className="text-muted-foreground hover:text-foreground hover:underline"
            >
              {team.name}
            </Link>
          );
        }
        return <span className="text-muted-foreground">{team ? team.name : "—"}</span>;
      },
    },
    {
      key: "description",
      header: "Description",
      className: "max-w-md truncate text-muted-foreground",
      cell: (project) => project.description || "—",
    },
    {
      key: "status",
      header: "Status",
      cell: (project) => (
        <StatusBadge variant={project.is_active ? "active" : "inactive"}>
          {project.is_active ? "Active" : "Archived"}
        </StatusBadge>
      ),
    },
    {
      key: "created",
      header: "Created",
      className: "text-muted-foreground",
      cell: (project) => (
        <span title={formatDateTime(project.created_at)}>
          {formatRelativeFromNow(project.created_at)}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      headClassName: "w-[1%]",
      cell: (project) =>
        canManageProject(project) ? (
          <div onClick={(event) => event.stopPropagation()}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Project actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditingProject(project)}>
                  <Pencil data-icon="inline-start" />
                  Edit project
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null,
    },
  ];

  return (
    <ResourceListPage
      title="Projects"
      description="Projects live inside teams and receive access and limit policies plus virtual keys."
      headerActions={
        <div className="flex items-center gap-2">
          {hasPermission(currentUser, "teams.manage") || hasAnyTeamAdminMembership(currentUser) ? (
            <Button asChild variant="outline">
              <Link to="/teams">
                <Building2 />
                Manage teams
              </Link>
            </Button>
          ) : null}
          {canCreateProject ? (
            <NewProjectSheet
              open={newOpen}
              onOpenChange={setNewOpen}
              activeTeams={activeTeams}
              disabled={!canCreate}
              onCreated={async (project) => {
                await queryClient.invalidateQueries();
                setNewOpen(false);
                toast.success(`Project "${project.name}" created.`);
                navigate(`/projects/${project.id}`);
              }}
            />
          ) : null}
        </div>
      }
      items={projects}
      isLoading={projectsQuery.isPending}
      getIsActive={(project) => project.is_active}
      getRowKey={(project) => project.id}
      noun="project"
      loadingLabel="Loading projects..."
      emptyIcon={FolderKanban}
      emptyTitle="No projects yet"
      emptyDescription={
        canCreate
          ? "Create the first project to start issuing virtual keys."
          : "You do not have project creation access in any active team."
      }
      emptyAction={
        canCreate ? (
          <Button onClick={() => setNewOpen(true)}>
            <Plus />
            New project
          </Button>
        ) : hasPermission(currentUser, "teams.manage") ? (
          <Button asChild>
            <Link to="/teams">
              <Building2 />
              Go to Teams
            </Link>
          </Button>
        ) : undefined
      }
      cardTitle="All projects"
      search={search}
      onSearchChange={setSearch}
      searchPlaceholder="Search projects..."
      matchesSearch={(project, term) => {
        const teamName = teamById[project.team_id]?.name ?? project.team_name ?? "";
        return `${project.name} ${project.description ?? ""} ${teamName}`
          .toLowerCase()
          .includes(term);
      }}
      segment={segment}
      onSegmentChange={setSegment}
      extraFilter={(project) => teamFilter === "all" || project.team_id === teamFilter}
      toolbarExtra={
        <Select value={teamFilter} onValueChange={setTeamFilter}>
          <SelectTrigger className="h-9 w-44" aria-label="Filter by team">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All teams</SelectItem>
            {teams.map((team) => (
              <SelectItem key={team.id} value={team.id}>
                {team.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
      columns={columns}
      renderCard={(project) => (
        <ProjectCard
          project={project}
          team={teamFor(project)}
          onOpen={() => navigate(`/projects/${project.id}`)}
          onEdit={() => setEditingProject(project)}
          canManage={canManageProject(project)}
          canOpenTeam={canViewTeam(currentUser, project.team_id)}
        />
      )}
      onRowClick={(project) => navigate(`/projects/${project.id}`)}
      rowClassName={(project) => (!project.is_active ? "opacity-60" : undefined)}
      noMatchTitle="No projects match"
      noMatchDescription="Try another search, status, or team."
      onClearFilters={() => {
        setSearch("");
        setSegment("active");
        setTeamFilter("all");
      }}
      editSheet={
        <EditProjectSheet
          project={editingProject}
          onClose={() => setEditingProject(null)}
          onUpdated={async () => {
            setEditingProject(null);
            await queryClient.invalidateQueries();
            toast.success("Project updated.");
          }}
        />
      }
    />
  );
}

function ProjectCard({
  project,
  team,
  onOpen,
  onEdit,
  canManage,
  canOpenTeam,
}: {
  project: ProjectResponse;
  team: Pick<TeamResponse, "id" | "name"> | undefined;
  onOpen: () => void;
  onEdit: () => void;
  canManage: boolean;
  canOpenTeam: boolean;
}) {
  return (
    <div
      role="button"
      aria-label={`Open project ${project.name}`}
      tabIndex={0}
      className={cn(
        "rounded-lg border bg-card p-4 shadow-sm transition-colors hover:bg-muted/30",
        !project.is_active && "opacity-70",
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
            to={`/projects/${project.id}`}
            onClick={(event) => event.stopPropagation()}
            className="font-medium underline-offset-4 hover:underline"
          >
            {project.name}
          </Link>
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
            {project.description || "No description."}
          </p>
        </div>
        {canManage ? (
          <div onClick={(event) => event.stopPropagation()}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Project actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={onEdit}>
                  <Pencil data-icon="inline-start" />
                  Edit project
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {team && canOpenTeam ? (
          <Link
            to={`/teams/${team.id}`}
            onClick={(event) => event.stopPropagation()}
            className="inline-flex items-center gap-1 rounded-md border px-2 py-1 hover:text-foreground"
          >
            <Building2 className="size-3" />
            {team.name}
          </Link>
        ) : team ? (
          <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1">
            <Building2 className="size-3" />
            {team.name}
          </span>
        ) : null}
        <StatusBadge variant={project.is_active ? "active" : "inactive"}>
          {project.is_active ? "Active" : "Archived"}
        </StatusBadge>
        <span title={formatDateTime(project.created_at)}>
          Created {formatRelativeFromNow(project.created_at)}
        </span>
      </div>
    </div>
  );
}

function EditProjectSheet({
  project,
  onClose,
  onUpdated,
}: {
  project: ProjectResponse | null;
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const form = useForm<Pick<NewProjectValues, "name" | "description">>({
    resolver: zodResolver(newProjectSchema.pick({ name: true, description: true })),
    defaultValues: { name: "", description: "" },
  });
  const updateProject = useUpdateProjectApiV1ProjectsProjectIdPatch({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) await onUpdated();
      },
      onError: (error) => toast.error(getProblemDetail(error, "Project could not be updated.")),
    },
  });

  useEffect(() => {
    if (!project) return;
    form.reset({ name: project.name, description: project.description ?? "" });
  }, [project, form]);

  const submit = form.handleSubmit((values) => {
    if (!project) return;
    updateProject.mutate({
      projectId: project.id,
      data: {
        name: values.name,
        description: values.description?.trim() ? values.description : null,
        is_active: project.is_active,
      },
    });
  });

  return (
    <Sheet open={Boolean(project)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit project</SheetTitle>
          <SheetDescription>Rename or update this project.</SheetDescription>
        </SheetHeader>
        <form
          id="edit-project-form"
          className="grid gap-4 overflow-y-auto px-6 py-5"
          onSubmit={submit}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-project-name">Name</Label>
            <Input id="edit-project-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-project-description">Description</Label>
            <Textarea id="edit-project-description" rows={4} {...form.register("description")} />
          </div>
        </form>
        <SheetFooter>
          <Button type="submit" form="edit-project-form" disabled={updateProject.isPending}>
            {updateProject.isPending ? "Saving..." : "Save changes"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function NewProjectSheet({
  open,
  onOpenChange,
  activeTeams,
  disabled,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeTeams: TeamResponse[];
  disabled: boolean;
  onCreated: (project: ProjectResponse) => Promise<void>;
}) {
  const form = useForm<NewProjectValues>({
    resolver: zodResolver(newProjectSchema),
    defaultValues: { teamId: "", name: "", description: "" },
  });
  const teamIdValue = useWatch({ control: form.control, name: "teamId" });

  const createProject = useCreateTeamProjectApiV1TeamsTeamIdProjectsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          form.reset();
          await onCreated(response.data);
        }
      },
      onError: (error) => toast.error(getProblemDetail(error, "Project could not be created.")),
    },
  });

  const submit = form.handleSubmit((values) =>
    createProject.mutate({
      teamId: values.teamId,
      data: {
        name: values.name,
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
        <Button disabled={disabled} title={disabled ? "Create an active team first." : undefined}>
          <Plus />
          New project
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>New project</SheetTitle>
          <SheetDescription>Pick a team to create this project in.</SheetDescription>
        </SheetHeader>
        <form
          id="new-project-form"
          className="grid gap-4 overflow-y-auto px-6 py-5"
          onSubmit={submit}
        >
          <div className="space-y-1.5">
            <Label htmlFor="new-project-team">Team</Label>
            <Select
              value={teamIdValue || undefined}
              onValueChange={(value) => form.setValue("teamId", value, { shouldValidate: true })}
            >
              <SelectTrigger id="new-project-team">
                <SelectValue placeholder="Select a team" />
              </SelectTrigger>
              <SelectContent>
                {activeTeams.map((team) => (
                  <SelectItem key={team.id} value={team.id}>
                    {team.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {form.formState.errors.teamId ? (
              <p className="text-xs text-destructive">{form.formState.errors.teamId.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-project-name">Name</Label>
            <Input id="new-project-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-project-description">Description</Label>
            <Textarea id="new-project-description" rows={4} {...form.register("description")} />
          </div>
        </form>
        <SheetFooter>
          <Button type="submit" form="new-project-form" disabled={createProject.isPending}>
            {createProject.isPending ? "Creating..." : "Create project"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
