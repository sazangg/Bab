import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, FolderKanban, MoreHorizontal, Pencil, Plus, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import {
  useCreateTeamProjectApiV1TeamsTeamIdProjectsPost,
  useDeactivateTeamApiV1TeamsTeamIdDelete,
  useGetTeamApiV1TeamsTeamIdGet,
  useListTeamProjectsApiV1TeamsTeamIdProjectsGet,
  useUpdateTeamApiV1TeamsTeamIdPatch,
} from "@/shared/api/generated/teams/teams";
import { Button } from "@/components/ui/button";
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
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

const projectSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(1000).optional(),
});

const editTeamSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().min(1).max(100),
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

  const projectForm = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: { name: "", description: "" },
  });
  const editTeamForm = useForm<EditTeamValues>({
    resolver: zodResolver(editTeamSchema),
    values: {
      name: team?.name ?? "",
      slug: team?.slug ?? "",
      description: team?.description ?? "",
    },
  });

  const createProject = useCreateTeamProjectApiV1TeamsTeamIdProjectsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          projectForm.reset();
          setProjectSheetOpen(false);
          await queryClient.invalidateQueries();
          navigate(`/projects/${response.data.id}`);
        }
      },
    },
  });
  const updateTeam = useUpdateTeamApiV1TeamsTeamIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditOpen(false);
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateTeam = useDeactivateTeamApiV1TeamsTeamIdDelete({
    mutation: {
      onSuccess: async () => {
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });

  if (teamQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading team...</p>;
  }
  if (!team) {
    return <PageHeader title="Team not found" description="The team may have been removed." />;
  }

  return (
    <>
      <PageHeader
        title={team.name}
        description={team.description ?? "No description."}
        actions={
          <>
            <StatusBadge variant={team.is_active ? "active" : "inactive"}>
              {team.is_active ? "Active" : "Archived"}
            </StatusBadge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Team actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                  <Pencil className="mr-2 size-4" />
                  Edit team
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setArchiveOpen(true)}
                  disabled={!team.is_active}
                >
                  <Archive className="mr-2 size-4" />
                  Archive team
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    updateTeam.mutate({ teamId: team.id, data: { is_active: true } })
                  }
                  disabled={team.is_active || updateTeam.isPending}
                >
                  <RotateCcw className="mr-2 size-4" />
                  Reactivate team
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Projects</h2>
            <p className="text-sm text-muted-foreground">
              Projects inside this team can receive allocations and issue virtual keys.
            </p>
          </div>
          <Sheet open={projectSheetOpen} onOpenChange={setProjectSheetOpen}>
            <SheetTrigger asChild>
              <Button>
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
                className="grid gap-4 px-4"
                onSubmit={projectForm.handleSubmit((values) =>
                  createProject.mutate({
                    teamId,
                    data: {
                      name: values.name,
                      description: values.description || null,
                    },
                  }),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="project-name">Name</Label>
                  <Input id="project-name" autoFocus {...projectForm.register("name")} />
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
        </div>

        {!projectsQuery.isPending && projects.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title="No projects yet"
            description="Create a project to start assigning allocations and keys."
            action={
              <Button onClick={() => setProjectSheetOpen(true)}>
                <Plus />
                New project
              </Button>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-lg border">
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
                  <TableRow
                    key={project.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/projects/${project.id}`)}
                  >
                    <TableCell className="font-medium">{project.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {project.description || "-"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge variant={project.is_active ? "active" : "inactive"}>
                        {project.is_active ? "Active" : "Archived"}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(project.created_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit team</DialogTitle>
            <DialogDescription>Rename or update this team.</DialogDescription>
          </DialogHeader>
          <form
            id="edit-team-form"
            className="grid gap-4"
            onSubmit={editTeamForm.handleSubmit((values) =>
              updateTeam.mutate({
                teamId: team.id,
                data: {
                  name: values.name,
                  slug: values.slug,
                  description: values.description || null,
                },
              }),
            )}
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-name">Name</Label>
              <Input id="edit-team-name" autoFocus {...editTeamForm.register("name")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-slug">Slug</Label>
              <Input id="edit-team-slug" {...editTeamForm.register("slug")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-team-description">Description</Label>
              <Textarea
                id="edit-team-description"
                rows={4}
                {...editTeamForm.register("description")}
              />
            </div>
          </form>
          <DialogFooter>
            <Button type="submit" form="edit-team-form" disabled={updateTeam.isPending}>
              {updateTeam.isPending ? "Saving..." : "Save changes"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive team?</DialogTitle>
            <DialogDescription>
              The team will remain visible, but it should no longer be used for new work.
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
    </>
  );
}
