import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import {
  useCreateProjectApiV1ProjectsPost,
  useListProjectsApiV1ProjectsGet,
} from "@/shared/api/generated/projects/projects";
import { Button } from "@/components/ui/button";
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

type ProjectFormValues = z.infer<typeof projectSchema>;

export function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const form = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: { name: "", description: "" },
  });
  const createMutation = useCreateProjectApiV1ProjectsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          form.reset();
          setOpen(false);
          await queryClient.invalidateQueries();
          navigate(`/projects/${response.data.id}`);
        }
      },
    },
  });

  return (
    <>
      <PageHeader
        title="Projects"
        description="Each project owns its providers, keys, and limits."
        actions={
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button>
                <Plus />
                New project
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>New project</SheetTitle>
                <SheetDescription>
                  A project groups keys and access rules for one application.
                </SheetDescription>
              </SheetHeader>
              <form
                className="grid gap-4 px-4"
                onSubmit={form.handleSubmit((values) =>
                  createMutation.mutate({
                    data: { name: values.name, description: values.description || null },
                  }),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="project-name">Name</Label>
                  <Input id="project-name" autoFocus {...form.register("name")} />
                  {form.formState.errors.name ? (
                    <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
                  ) : null}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="project-description">Description</Label>
                  <Textarea id="project-description" rows={4} {...form.register("description")} />
                </div>
                {createMutation.isError ? (
                  <p className="text-sm text-destructive">Project was not created.</p>
                ) : null}
              </form>
              <SheetFooter>
                <Button
                  type="submit"
                  disabled={createMutation.isPending}
                  onClick={form.handleSubmit((values) =>
                    createMutation.mutate({
                      data: { name: values.name, description: values.description || null },
                    }),
                  )}
                >
                  {createMutation.isPending ? "Creating..." : "Create project"}
                </Button>
                <SheetClose asChild>
                  <Button variant="outline">Cancel</Button>
                </SheetClose>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        }
      />

      {!projectsQuery.isPending && projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Create your first project to start issuing virtual keys."
          action={
            <Button onClick={() => setOpen(true)}>
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
                    {project.description || "—"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={project.is_active ? "active" : "inactive"}>
                      {project.is_active ? "Active" : "Inactive"}
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
    </>
  );
}
