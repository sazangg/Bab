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
import { DataTable } from "@/components/ui/data-table";
import { Textarea } from "@/components/ui/textarea";
import { MembersCard } from "@/shared/components/MembersCard";
import { formatCents } from "@/shared/lib/format-currency";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { getProblemDetail } from "@/shared/api/problem-detail";
import {
  useAddTeamMemberApiV1TeamsTeamIdMembersPost,
  useCreateTeamProjectApiV1TeamsTeamIdProjectsPost,
  useDeactivateTeamApiV1TeamsTeamIdDelete,
  useGetTeamArchiveImpactApiV1TeamsTeamIdArchiveImpactGet,
  useGetTeamApiV1TeamsTeamIdGet,
  useGetTeamUsageApiV1TeamsTeamIdUsageGet,
  useListTeamMembersApiV1TeamsTeamIdMembersGet,
  useListTeamProjectsApiV1TeamsTeamIdProjectsGet,
  useRemoveTeamMemberApiV1TeamsTeamIdMembersUserIdDelete,
  useUpdateTeamMemberApiV1TeamsTeamIdMembersUserIdPatch,
  useUpdateTeamApiV1TeamsTeamIdPatch,
} from "@/shared/api/generated/teams/teams";
import type { TeamMemberResponse, UpdateTeamRequest } from "@/shared/api/generated/schemas";

import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";
import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";
import { hasPermission, isTeamAdmin } from "@/features/auth/lib/permissions";
import { useTeamMemberOptions } from "@/features/auth/lib/member-options";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";
import { slugify } from "@/features/teams/lib/slug";
import { EntityUsageCard } from "@/features/usage/components/EntityUsageCard";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";

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
  const [selfRemoval, setSelfRemoval] = useState<TeamMemberResponse | null>(null);
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;

  const teamQuery = useGetTeamApiV1TeamsTeamIdGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const projectsQuery = useListTeamProjectsApiV1TeamsTeamIdProjectsGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const teamMembersQuery = useListTeamMembersApiV1TeamsTeamIdMembersGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const usageQuery = useGetTeamUsageApiV1TeamsTeamIdUsageGet(teamId, {
    query: { enabled: Boolean(teamId) },
  });
  const archiveImpactQuery = useGetTeamArchiveImpactApiV1TeamsTeamIdArchiveImpactGet(teamId, {
    query: { enabled: archiveOpen && Boolean(teamId) },
  });
  const team = teamQuery.data?.status === 200 ? teamQuery.data.data : undefined;
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamMembers = teamMembersQuery.data?.status === 200 ? teamMembersQuery.data.data : [];
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const archiveImpact =
    archiveImpactQuery.data?.status === 200 ? archiveImpactQuery.data.data : null;
  const activeProjectCount = projects.filter((p) => p.is_active).length;
  const canManageTeam =
    team !== undefined &&
    (hasPermission(currentUser, "teams.manage") || isTeamAdmin(currentUser, team.id));
  const canManageTeamPolicies = canManageTeam;
  const memberOptionsQuery = useTeamMemberOptions(teamId, canManageTeam);
  const orgMembers = memberOptionsQuery.data ?? [];

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
      onError: (error) => toast.error(getProblemDetail(error, "Project could not be created.")),
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
      onError: (error) => toast.error(getProblemDetail(error, "Team could not be archived.")),
    },
  });
  const addTeamMember = useAddTeamMemberApiV1TeamsTeamIdMembersPost({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Team member added.");
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Team member could not be added.")),
    },
  });
  const updateTeamMember = useUpdateTeamMemberApiV1TeamsTeamIdMembersUserIdPatch({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Team role updated.");
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Team role could not be updated.")),
    },
  });
  const removeTeamMember = useRemoveTeamMemberApiV1TeamsTeamIdMembersUserIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Team member removed.");
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Team member could not be removed.")),
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
  if (isAxiosError(teamQuery.error) && teamQuery.error.response?.status === 403) {
    return <ForbiddenPage />;
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
          canManageTeam ? (
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
          ) : null
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

      <MembersCard
        title="Members"
        description="Team roles are scoped to this team. Org owners and admins still keep their org-level access."
        orgMembers={orgMembers}
        members={teamMembers}
        roleOptions={[
          { value: "team_admin", label: "Team admin" },
          { value: "team_member", label: "Team member" },
        ]}
        defaultRole="team_member"
        roleLabel="Team role"
        getRole={(member) => member.team_role}
        canManage={canManageTeam}
        isLoading={memberOptionsQuery.isPending || teamMembersQuery.isPending}
        isPending={
          addTeamMember.isPending || updateTeamMember.isPending || removeTeamMember.isPending
        }
        onAdd={(userId, role) => addTeamMember.mutate({ teamId, data: { user_id: userId, role } })}
        onRoleChange={(member, role) =>
          updateTeamMember.mutate({ teamId, userId: member.user_id, data: { role } })
        }
        onRemove={(member) => {
          if (member.user_id === currentUser?.id) {
            setSelfRemoval(member);
            return;
          }
          removeTeamMember.mutate({ teamId, userId: member.user_id });
        }}
        removeAriaLabel={(member) =>
          member.user_id === currentUser?.id ? "Remove yourself from team" : "Remove team member"
        }
        emptyTitle="No team members assigned"
        emptyDescription="Assign existing organization members to make team access explicit."
      />

      <EntityUsageCard
        usage={usage}
        isLoading={usageQuery.isPending}
        description="Aggregate team usage across projects, virtual keys, and inherited policies."
      />
      <UsageRecordsDrilldown title="Team usage records" filters={{ team_id: team.id }} />

      <PolicyScopeSection
        target={{ type: "team", teamId: team.id }}
        canManage={canManageTeamPolicies}
      />

      <Card>
        <CardHeader>
          <CardTitle>Projects</CardTitle>
          <CardDescription>
            Projects inside this team receive policies and issue virtual keys.
          </CardDescription>
          <CardAction>
            {canManageTeam ? (
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
            ) : null}
          </CardAction>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={[
              { key: "name", header: "Name", className: "font-medium", cell: (project) => project.name },
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
                    {new Date(project.created_at).toLocaleDateString()}
                  </span>
                ),
              },
            ]}
            data={projects}
            loading={projectsQuery.isPending}
            getRowKey={(project) => project.id}
            onRowClick={(project) => navigate(`/projects/${project.id}`)}
            rowClassName={(project) => (!project.is_active ? "opacity-60" : undefined)}
            empty={{
              title: "No projects yet",
              description: "Create a project to start assigning policies and keys.",
              action:
                canManageTeam ? (
                  <Button size="sm" onClick={() => setProjectSheetOpen(true)} disabled={!team.is_active}>
                    <Plus />
                    New project
                  </Button>
                ) : undefined,
            }}
          />
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
                <p className="text-xs text-warning">
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
              Descendant projects and virtual keys will stop serving gateway traffic immediately.
              Records and analytics stay visible.
            </DialogDescription>
          </DialogHeader>
          {archiveImpactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Checking impact...</p>
          ) : archiveImpact ? (
            <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm md:grid-cols-2">
              <Fact label="Active projects" value={`${archiveImpact.active_project_count}`} />
              <Fact label="Active keys" value={`${archiveImpact.active_virtual_key_count}`} />
              <Fact
                label={`${archiveImpact.recent_usage_window_days}d requests`}
                value={(archiveImpact.recent_request_count ?? 0).toLocaleString()}
              />
              <Fact label="Estimated spend" value={formatCents(archiveImpact.recent_cost_cents)} />
              <Fact label="Team admins" value={`${archiveImpact.team_admin_count}`} />
              <Fact label="Team members" value={`${archiveImpact.team_member_count}`} />
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-destructive">Impact could not be loaded.</p>
              <Button variant="outline" size="sm" onClick={() => archiveImpactQuery.refetch()}>
                Retry
              </Button>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={deactivateTeam.isPending || !archiveImpact}
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

      <Dialog open={Boolean(selfRemoval)} onOpenChange={(open) => !open && setSelfRemoval(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove your team access?</DialogTitle>
            <DialogDescription>
              You are removing yourself from {team.name}. If this is your only scoped role, you may
              lose access to this team and its projects immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={removeTeamMember.isPending}
              onClick={() => {
                if (!selfRemoval) return;
                removeTeamMember.mutate(
                  { teamId, userId: selfRemoval.user_id },
                  { onSuccess: () => setSelfRemoval(null) },
                );
              }}
            >
              {removeTeamMember.isPending ? "Removing..." : "Remove my access"}
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

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

