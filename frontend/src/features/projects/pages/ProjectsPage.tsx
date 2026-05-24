import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  FolderKanban,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

import {
  useDeactivateProjectApiV1ProjectsProjectIdDelete,
  useListProjectsApiV1ProjectsGet,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
import {
  useCreateTeamProjectApiV1TeamsTeamIdProjectsPost,
  useListTeamsApiV1TeamsGet,
} from "@/shared/api/generated/teams/teams";
import type { ProjectResponse, TeamResponse } from "@/shared/api/generated/schemas";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";

type ProjectSegment = "all" | "active" | "archived";

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
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamsData = teamsQuery.data?.status === 200 ? teamsQuery.data.data : undefined;
  const teams = useMemo(() => teamsData ?? [], [teamsData]);
  const activeTeams = useMemo(() => teams.filter((team) => team.is_active), [teams]);
  const teamById = useMemo(() => {
    const map: Record<string, TeamResponse> = {};
    for (const team of teams) {
      map[team.id] = team;
    }
    return map;
  }, [teams]);

  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<ProjectSegment>("active");
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [newOpen, setNewOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectResponse | null>(null);

  const segmentCounts = {
    all: projects.length,
    active: projects.filter((p) => p.is_active).length,
    archived: projects.filter((p) => !p.is_active).length,
  };
  const filtered = projects
    .filter((project) => {
      if (segment === "active") return project.is_active;
      if (segment === "archived") return !project.is_active;
      return true;
    })
    .filter((project) => teamFilter === "all" || project.team_id === teamFilter)
    .filter((project) => {
      const term = search.toLowerCase().trim();
      if (!term) return true;
      const teamName = teamById[project.team_id]?.name ?? "";
      return `${project.name} ${project.description ?? ""} ${teamName}`
        .toLowerCase()
        .includes(term);
    });

  const canCreate = activeTeams.length > 0;

  return (
    <>
      <PageHeader
        title="Projects"
        description="Projects live inside teams and receive provider allocations + virtual keys."
        actions={
          <div className="flex items-center gap-2">
            <Button asChild variant="outline">
              <Link to="/teams">
                <Building2 />
                Manage teams
              </Link>
            </Button>
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
          </div>
        }
      />

      {projectsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading projects...</p>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description={
            canCreate
              ? "Create the first project to start issuing virtual keys."
              : "Create an active team first, then add projects to it."
          }
          action={
            canCreate ? (
              <Button onClick={() => setNewOpen(true)}>
                <Plus />
                New project
              </Button>
            ) : (
              <Button asChild>
                <Link to="/teams">
                  <Building2 />
                  Go to Teams
                </Link>
              </Button>
            )
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All projects</CardTitle>
            <CardDescription>
              {projects.length} {projects.length === 1 ? "project" : "projects"} ·{" "}
              {segmentCounts.active} active · {segmentCounts.archived} archived
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative max-w-md flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search projects..."
                />
              </div>
              <div className="flex items-center gap-2">
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
                <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
                  {(["all", "active", "archived"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSegment(value)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                        segment === value
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {value}
                      <span className="ml-1.5 text-muted-foreground">{segmentCounts[value]}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {filtered.length === 0 ? (
              <div className="rounded-md border border-dashed p-8 text-center">
                <p className="text-sm font-medium">No projects match</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Try another search, status, or team.
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Team</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead className="w-[1%]" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((project) => (
                      <ProjectRow
                        key={project.id}
                        project={project}
                        team={teamById[project.team_id]}
                        onOpen={() => navigate(`/projects/${project.id}`)}
                        onEdit={() => setEditingProject(project)}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      <EditProjectSheet
        project={editingProject}
        onClose={() => setEditingProject(null)}
        onUpdated={async () => {
          setEditingProject(null);
          await queryClient.invalidateQueries();
          toast.success("Project updated.");
        }}
      />
    </>
  );
}

function ProjectRow({
  project,
  team,
  onOpen,
  onEdit,
}: {
  project: ProjectResponse;
  team: TeamResponse | undefined;
  onOpen: () => void;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const deactivateProject = useDeactivateProjectApiV1ProjectsProjectIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Project archived.");
      },
      onError: () => toast.error("Project could not be archived."),
    },
  });
  return (
    <TableRow
      className={cn("cursor-pointer", !project.is_active && "opacity-60")}
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <TableCell className="font-medium">{project.name}</TableCell>
      <TableCell>
        {team ? (
          <Link
            to={`/teams/${team.id}`}
            onClick={(event) => event.stopPropagation()}
            className="text-muted-foreground hover:text-foreground hover:underline"
          >
            {team.name}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="max-w-md truncate text-muted-foreground">
        {project.description || "—"}
      </TableCell>
      <TableCell>
        <StatusBadge variant={project.is_active ? "active" : "inactive"}>
          {project.is_active ? "Active" : "Archived"}
        </StatusBadge>
      </TableCell>
      <TableCell className="text-muted-foreground" title={formatDateTime(project.created_at)}>
        {formatRelativeFromNow(project.created_at)}
      </TableCell>
      <TableCell onClick={(event) => event.stopPropagation()}>
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
            <DropdownMenuItem
              variant="destructive"
              disabled={!project.is_active || deactivateProject.isPending}
              onSelect={() => deactivateProject.mutate({ projectId: project.id })}
            >
              <Trash2 data-icon="inline-start" />
              Archive project
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
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
      onError: () => toast.error("Project could not be updated."),
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
      onError: () => toast.error("Project could not be created."),
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
