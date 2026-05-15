import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import {
  useCreateTeamApiV1TeamsPost,
  useListTeamsApiV1TeamsGet,
} from "@/shared/api/generated/teams/teams";
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

const teamSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().max(100).optional(),
  description: z.string().max(1000).optional(),
});

type TeamFormValues = z.infer<typeof teamSchema>;

export function TeamsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const form = useForm<TeamFormValues>({
    resolver: zodResolver(teamSchema),
    defaultValues: { name: "", slug: "", description: "" },
  });
  const createTeam = useCreateTeamApiV1TeamsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          form.reset();
          setOpen(false);
          await queryClient.invalidateQueries();
          navigate(`/teams/${response.data.id}`);
        }
      },
    },
  });

  const submit = form.handleSubmit((values) =>
    createTeam.mutate({
      data: {
        name: values.name,
        slug: values.slug || null,
        description: values.description || null,
      },
    }),
  );

  return (
    <>
      <PageHeader
        title="Teams"
        description="Teams group projects under a business, product, or division boundary."
        actions={
          <Sheet open={open} onOpenChange={setOpen}>
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
              <form id="create-team-form" className="grid gap-4 px-4" onSubmit={submit}>
                <div className="space-y-1.5">
                  <Label htmlFor="team-name">Name</Label>
                  <Input id="team-name" autoFocus {...form.register("name")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-slug">Slug</Label>
                  <Input id="team-slug" placeholder="mobile-division" {...form.register("slug")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-description">Description</Label>
                  <Textarea id="team-description" rows={4} {...form.register("description")} />
                </div>
                {createTeam.isError ? (
                  <p className="text-sm text-destructive">Team was not created.</p>
                ) : null}
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
        }
      />

      {!teamsQuery.isPending && teams.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No teams yet"
          description="Create the first team to start organizing projects."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus />
              New team
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {teams.map((team) => (
                <TableRow
                  key={team.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/teams/${team.id}`)}
                >
                  <TableCell className="font-medium">{team.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {team.slug}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {team.description || "-"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={team.is_active ? "active" : "inactive"}>
                      {team.is_active ? "Active" : "Inactive"}
                    </StatusBadge>
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
