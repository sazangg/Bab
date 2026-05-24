import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Archive, MoreHorizontal, Pencil, Plus, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import {
  useCreateTeamProjectApiV1TeamsTeamIdProjectsPost,
  useDeactivateTeamApiV1TeamsTeamIdDelete,
  useGetTeamApiV1TeamsTeamIdGet,
  useListTeamProjectsApiV1TeamsTeamIdProjectsGet,
  useUpdateTeamApiV1TeamsTeamIdPatch,
} from "@/shared/api/generated/teams/teams";
import type { ProjectResponse, UpdateTeamRequest } from "@/shared/api/generated/schemas";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";
import { AllocationManagementSection } from "@/features/projects/sections/AllocationManagementSection";
import { slugify } from "@/features/teams/lib/slug";

const projectSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional(),
});

const editTeamSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(100)
    .regex(/^[a-z0-9-]+$/, "Use lowercase letters, numbers, and dashes only"),
  description: z.string().max(1000).optional(),
});

type ProjectFormValues = z.infer<typeof projectSchema>;
type EditTeamValues = z.infer<typeof editTeamSchema>;

export function TeamDetailPage() {
  const { teamId = "" } = useParams<{ teamId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [projectSheetOpen, setProjectSheetOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const teamQuery = useGetTeamApiV1TeamsTeamIdGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const projectsQuery = useListTeamProjectsApiV1TeamsTeamIdProjectsGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const team = teamQuery.data?.status === 200 ? teamQuery.data.data : undefined;
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const activeProjectCount = projects.filter((p) => p.is_active).length;

  const projectForm = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: { name: "", description: "" },
  });
  const editTeamForm = useForm<EditTeamValues>({
    resolver: zodResolver(editTeamSchema),
    defaultValues: { name: "", slug: "", description: "" },
  });

  useEffect(() => {
    if (editOpen && team) {
      editTeamForm.reset({
        name: team.name,
        slug: team.slug,
        description: team.description ?? "",
      });
    }
  }, [editOpen, team, editTeamForm]);

  const createProject = useCreateTeamProjectApiV1TeamsTeamIdProjectsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          projectForm.reset();
          setProjectSheetOpen(false);
          await queryClient.invalidateQueries();
          toast.success(`Project "${response.data.name}" created.`);
        }
      },
      onError: () => toast.error("Project could not be created."),
    },
  });
  const updateTeam = useUpdateTeamApiV1TeamsTeamIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditOpen(false);
        await queryClient.invalidateQueries();
        toast.success("Team updated.");
      },
      onError: (error) => {
        if (isAxiosError(error) && error.response?.status === 409) {
          editTeamForm.setError("slug", {
            type: "server",
            message: "A team with this slug already exists.",
          });
          toast.error("Slug already in use. Pick another.");
          return;
        }
        toast.error("Team could not be updated.");
      },
    },
  });
  const reactivateTeam = useUpdateTeamApiV1TeamsTeamIdPatch({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Team reactivated.");
      },
      onError: () => toast.error("Reactivation failed."),
    },
  });
  const deactivateTeam = useDeactivateTeamApiV1TeamsTeamIdDelete({
    mutation: {
      onSuccess: async () => {
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
        toast.success("Team archived.");
      },
      onError: () => toast.error("Archive failed."),
    },
  });

  const slugInput = useWatch({ control: editTeamForm.control, name: "slug" });
  const slugPreview = slugInput?.trim() ? slugify(slugInput) : "";
  const slugChanged = team && slugInput !== team.slug;

  const submitEdit = editTeamForm.handleSubmit((values) => {
    if (!team) return;
    const dirty = editTeamForm.formState.dirtyFields;
    const payload: UpdateTeamRequest = {};
    if (dirty.name) payload.name = values.name;
    if (dirty.slug) payload.slug = values.slug;
    if (dirty.description) {
      payload.description = values.description?.trim() ? values.description : null;
    }
    if (Object.keys(payload).length === 0) {
      setEditOpen(false);
      return;
    }
    updateTeam.mutate({ teamId: team.id, data: payload });
  });

  if (teamQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading team...</p>;
  }
  if (!team) {
    return <PageHeader title="Team not found" description="The team may have been removed." />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={team.name}
        description={team.description ?? "Group projects under this team."}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil />
              Edit team
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Team actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() => setArchiveOpen(true)}
                  disabled={!team.is_active}
                  variant="destructive"
                >
                  <Archive className="mr-2 size-4" />
                  Archive team
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    reactivateTeam.mutate({ teamId: team.id, data: { is_active: true } })
                  }
                  disabled={team.is_active || reactivateTeam.isPending}
                >
                  <RotateCcw className="mr-2 size-4" />
                  Reactivate team
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Team summary</CardTitle>
          <CardDescription className="font-mono text-xs">{team.slug}</CardDescription>
          <CardAction>
            <StatusBadge variant={team.is_active ? "active" : "inactive"}>
              {team.is_active ? "Active" : "Archived"}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact label="Projects" value={`${activeProjectCount} active`} />
          <Fact label="Total projects" value={`${projects.length}`} />
          <Fact label="Created" value={formatRelativeFromNow(team.created_at)} />
          <Fact label="Updated" value={formatRelativeFromNow(team.updated_at)} />
        </CardContent>
      </Card>

      <AllocationManagementSection target={{ type: "team", teamId: team.id }} />

      <Card>
        <CardHeader>
          <CardTitle>Projects</CardTitle>
          <CardDescription>
            Projects inside this team receive allocations and issue virtual keys.
          </CardDescription>
          <CardAction>
            <Sheet
              open={projectSheetOpen}
              onOpenChange={(next) => {
                setProjectSheetOpen(next);
                if (!next) projectForm.reset();
              }}
            >
              <SheetTrigger asChild>
                <Button
                  size="sm"
                  disabled={!team.is_active}
                  title={team.is_active ? undefined : "Reactivate the team to add projects."}
                >
                  <Plus />
                  New project
                </Button>
              </SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>New project</SheetTitle>
                  <SheetDescription>Create a project under {team.name}.</SheetDescription>
                </SheetHeader>
                <form
                  id="create-project-form"
                  className="grid gap-4 overflow-y-auto px-6 py-5"
                  onSubmit={projectForm.handleSubmit((values) =>
                    createProject.mutate({
                      teamId,
                      data: {
                        name: values.name,
                        description: values.description?.trim() ? values.description : null,
                      },
                    }),
                  )}
                >
                  <div className="space-y-1.5">
                    <Label htmlFor="project-name">Name</Label>
                    <Input id="project-name" autoFocus {...projectForm.register("name")} />
                    {projectForm.formState.errors.name ? (
                      <p className="text-xs text-destructive">
                        {projectForm.formState.errors.name.message}
                      </p>
                    ) : null}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="project-description">Description</Label>
                    <Textarea
                      id="project-description"
                      rows={4}
                      {...projectForm.register("description")}
                    />
                  </div>
                </form>
                <SheetFooter>
                  <Button
                    type="submit"
                    form="create-project-form"
                    disabled={createProject.isPending}
                  >
                    {createProject.isPending ? "Creating..." : "Create project"}
                  </Button>
                  <SheetClose asChild>
                    <Button variant="outline">Cancel</Button>
                  </SheetClose>
                </SheetFooter>
              </SheetContent>
            </Sheet>
          </CardAction>
        </CardHeader>
        <CardContent>
          {projectsQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading projects...</p>
          ) : projects.length === 0 ? (
            <div className="rounded-md border border-dashed p-8 text-center">
              <p className="text-sm font-medium">No projects yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Create a project to start assigning allocations and keys.
              </p>
              <Button
                className="mt-4"
                size="sm"
                onClick={() => setProjectSheetOpen(true)}
                disabled={!team.is_active}
              >
                <Plus />
                New project
              </Button>
            </div>
          ) : (
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projects.map((project) => (
                    <ProjectTableRow
                      key={project.id}
                      project={project}
                      onOpen={() => navigate(`/projects/${project.id}`)}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Sheet open={editOpen} onOpenChange={setEditOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit team</SheetTitle>
            <SheetDescription>Rename or update this team.</SheetDescription>
          </SheetHeader>
          <form
            id="edit-team-form"
            className="grid gap-4 overflow-y-auto px-6 py-5"
            onSubmit={submitEdit}
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-name">Name</Label>
              <Input id="edit-team-name" autoFocus {...editTeamForm.register("name")} />
              {editTeamForm.formState.errors.name ? (
                <p className="text-xs text-destructive">
                  {editTeamForm.formState.errors.name.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-slug">Slug</Label>
              <Input id="edit-team-slug" {...editTeamForm.register("slug")} />
              {editTeamForm.formState.errors.slug ? (
                <p className="text-xs text-destructive">
                  {editTeamForm.formState.errors.slug.message}
                </p>
              ) : slugChanged && slugPreview ? (
                <p className="text-xs text-amber-600 dark:text-amber-500">
                  Changing the slug will break links that reference{" "}
                  <span className="font-mono">{team.slug}</span>.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Used in URLs and attribution.</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-description">Description</Label>
              <Textarea
                id="edit-team-description"
                rows={4}
                {...editTeamForm.register("description")}
              />
              {editTeamForm.formState.errors.description ? (
                <p className="text-xs text-destructive">
                  {editTeamForm.formState.errors.description.message}
                </p>
              ) : null}
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

      <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive {team.name}?</DialogTitle>
            <DialogDescription>
              Archived teams stay visible but cannot have new projects created in them. Existing
              projects are unaffected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={deactivateTeam.isPending}
              onClick={() => deactivateTeam.mutate({ teamId: team.id })}
            >
              {deactivateTeam.isPending ? "Archiving..." : "Archive team"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProjectTableRow({ project, onOpen }: { project: ProjectResponse; onOpen: () => void }) {
  return (
    <TableRow className={cn("cursor-pointer", !project.is_active && "opacity-60")} onClick={onOpen}>
      <TableCell className="font-medium">{project.name}</TableCell>
      <TableCell className="max-w-md truncate text-muted-foreground">
        {project.description || "—"}
      </TableCell>
      <TableCell>
        <StatusBadge variant={project.is_active ? "active" : "inactive"}>
          {project.is_active ? "Active" : "Archived"}
        </StatusBadge>
      </TableCell>
      <TableCell className="text-muted-foreground" title={formatDateTime(project.created_at)}>
        {new Date(project.created_at).toLocaleDateString()}
      </TableCell>
    </TableRow>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}
