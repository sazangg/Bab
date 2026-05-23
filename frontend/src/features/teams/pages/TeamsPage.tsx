import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Building2, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import {
  useCreateTeamApiV1TeamsPost,
  useListTeamsApiV1TeamsGet,
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
type TeamSegment = "all" | "active" | "archived";

export function TeamsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<TeamSegment>("active");

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

  const segmentCounts = {
    all: teams.length,
    active: teams.filter((t) => t.is_active).length,
    archived: teams.filter((t) => !t.is_active).length,
  };
  const filtered = teams
    .filter((team) => {
      if (segment === "active") return team.is_active;
      if (segment === "archived") return !team.is_active;
      return true;
    })
    .filter((team) =>
      `${team.name} ${team.slug} ${team.description ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
    );

  return (
    <>
      <PageHeader
        title="Teams"
        description="Teams group projects under a business, product, or division boundary."
        actions={
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
        }
      />

      {teamsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading teams...</p>
      ) : teams.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No teams yet"
          description="Create the first team to start organizing projects."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus />
              New team
            </Button>
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All teams</CardTitle>
            <CardDescription>
              {teams.length} {teams.length === 1 ? "team" : "teams"} · {segmentCounts.active} active
              · {segmentCounts.archived} archived
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
                  placeholder="Search teams..."
                />
              </div>
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

            {filtered.length === 0 ? (
              <div className="rounded-md border border-dashed p-8 text-center">
                <p className="text-sm font-medium">No teams match</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Try a different search or status.
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Slug</TableHead>
                      <TableHead className="text-right">Projects</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Updated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((team) => (
                      <TeamRow
                        key={team.id}
                        team={team}
                        projectCount={projectCountByTeam[team.id] ?? 0}
                        onOpen={() => navigate(`/teams/${team.id}`)}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}

function TeamRow({
  team,
  projectCount,
  onOpen,
}: {
  team: TeamResponse;
  projectCount: number;
  onOpen: () => void;
}) {
  return (
    <TableRow
      className={cn("cursor-pointer", !team.is_active && "opacity-60")}
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <TableCell className="font-medium">{team.name}</TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{team.slug}</TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground">
        {projectCount}
      </TableCell>
      <TableCell className="max-w-md truncate text-muted-foreground">
        {team.description || "—"}
      </TableCell>
      <TableCell>
        <StatusBadge variant={team.is_active ? "active" : "inactive"}>
          {team.is_active ? "Active" : "Archived"}
        </StatusBadge>
      </TableCell>
      <TableCell className="text-muted-foreground" title={formatDateTime(team.updated_at)}>
        {formatRelativeFromNow(team.updated_at)}
      </TableCell>
    </TableRow>
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
        <form id="create-team-form" className="grid gap-4 px-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="team-name">Name</Label>
            <Input id="team-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="team-slug">Slug</Label>
            <Input id="team-slug" placeholder="mobile-division" {...form.register("slug")} />
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
