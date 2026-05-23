import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { ProjectResponse, UpdateProjectRequest } from "@/shared/api/generated/schemas";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const editSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(1000).optional(),
});

type EditValues = z.infer<typeof editSchema>;

export function EditProjectDialog({
  open,
  onOpenChange,
  project,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project: ProjectResponse;
  onSubmit: (data: UpdateProjectRequest) => void;
  isPending: boolean;
}) {
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { name: project.name, description: project.description ?? "" },
  });

  useEffect(() => {
    if (open) {
      form.reset({ name: project.name, description: project.description ?? "" });
    }
  }, [open, project, form]);

  const handleSubmit = form.handleSubmit((values) => {
    const dirty = form.formState.dirtyFields;
    const payload: UpdateProjectRequest = {};
    if (dirty.name) payload.name = values.name;
    if (dirty.description)
      payload.description = values.description?.trim() ? values.description : null;
    if (Object.keys(payload).length === 0) {
      onOpenChange(false);
      return;
    }
    onSubmit(payload);
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit project</DialogTitle>
          <DialogDescription>Rename or update the description.</DialogDescription>
        </DialogHeader>
        <form id="edit-project-form" className="grid gap-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="edit-project-name">Name</Label>
            <Input id="edit-project-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-project-description">Description</Label>
            <Textarea id="edit-project-description" rows={4} {...form.register("description")} />
            {form.formState.errors.description ? (
              <p className="text-xs text-destructive">
                {form.formState.errors.description.message}
              </p>
            ) : null}
          </div>
        </form>
        <DialogFooter>
          <Button type="submit" form="edit-project-form" disabled={isPending}>
            {isPending ? "Saving..." : "Save changes"}
          </Button>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
