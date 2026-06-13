import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Archive, Building2, KeyRound, MoreHorizontal, Pencil, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import {
  useDeactivateProjectApiV1ProjectsProjectIdDelete,
  useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet,
  useGetProjectArchiveImpactApiV1ProjectsProjectIdArchiveImpactGet,
  useGetProjectApiV1ProjectsProjectIdGet,
  useGetProjectUsageApiV1ProjectsProjectIdUsageGet,
  useAddProjectMemberApiV1ProjectsProjectIdMembersPost,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useListProjectMembersApiV1ProjectsProjectIdMembersGet,
  useRemoveProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete,
  useUpdateProjectMemberApiV1ProjectsProjectIdMembersUserIdPatch,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { ProjectAccessSection } from "@/features/projects/sections/ProjectAccessSection";
import { ProjectKeysSection } from "@/features/projects/sections/ProjectKeysSection";
import { EditProjectDialog } from "@/features/projects/components/EditProjectDialog";
import { EntityUsageCard } from "@/features/usage/components/EntityUsageCard";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";
import {
  canViewTeam,
  hasPermission,
  isProjectAdmin,
  isTeamAdmin,
} from "@/features/auth/lib/permissions";
import { useProjectMemberOptions } from "@/features/auth/lib/member-options";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";
import { RecentGuardrailEventsCard } from "@/features/guardrails/components/RecentGuardrailEventsCard";
import { MembersCard } from "@/shared/components/MembersCard";
import type { EffectiveAccessSummary } from "@/shared/api/generated/schemas";
import { getProblemDetail } from "@/shared/api/problem-detail";

export function ProjectDetailPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const projectQuery = useGetProjectApiV1ProjectsProjectIdGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const project = projectQuery.data?.status === 200 ? projectQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageProject = project
    ? hasPermission(currentUser, "projects.manage") ||
      isTeamAdmin(currentUser, project.team_id) ||
      isProjectAdmin(currentUser, project.id)
    : false;
  const memberOptionsQuery = useProjectMemberOptions(projectId, canManageProject);
  const projectMembersQuery = useListProjectMembersApiV1ProjectsProjectIdMembersGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const keysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const usageQuery = useGetProjectUsageApiV1ProjectsProjectIdUsageGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const archiveImpactQuery = useGetProjectArchiveImpactApiV1ProjectsProjectIdArchiveImpactGet(
    projectId,
    { query: { enabled: archiveOpen && Boolean(projectId) } },
  );
  const effectiveAccessQuery = useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet(
    projectId,
    { query: { enabled: Boolean(projectId) } },
  );

  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const orgMembers = memberOptionsQuery.data ?? [];
  const projectMembers =
    projectMembersQuery.data?.status === 200 ? projectMembersQuery.data.data : [];
  const team = project
    ? (teams.find((item) => item.id === project.team_id) ??
      (project.team_name
        ? { id: project.team_id, name: project.team_name, is_active: true }
        : undefined))
    : undefined;
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const archiveImpact =
    archiveImpactQuery.data?.status === 200 ? archiveImpactQuery.data.data : null;
  const effectiveAccess =
    effectiveAccessQuery.data?.status === 200 ? effectiveAccessQuery.data.data : undefined;
  const canArchiveProject = canManageProject;
  const requestedTab = searchParams.get("tab");
  const activeTab =
    requestedTab === "keys" || requestedTab === "access" || requestedTab === "members"
      ? requestedTab
      : "overview";

  const updateMutation = useUpdateProjectApiV1ProjectsProjectIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditOpen(false);
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
      },
      onError: (error) => toast.error(getProblemDetail(error, "Project could not be updated.")),
    },
  });
  const deactivateMutation = useDeactivateProjectApiV1ProjectsProjectIdDelete({
    mutation: {
      onSuccess: async () => {
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
        navigate("/projects");
      },
      onError: (error) => toast.error(getProblemDetail(error, "Project could not be archived.")),
    },
  });
  const addProjectMemberMutation = useAddProjectMemberApiV1ProjectsProjectIdMembersPost({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Project member could not be added.")),
    },
  });
  const removeProjectMemberMutation =
    useRemoveProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete({
      mutation: {
        onSuccess: async () => {
          await queryClient.invalidateQueries();
        },
        onError: (error) =>
          toast.error(getProblemDetail(error, "Project member could not be removed.")),
      },
    });
  const updateProjectMemberMutation =
    useUpdateProjectMemberApiV1ProjectsProjectIdMembersUserIdPatch({
      mutation: {
        onSuccess: async () => {
          await queryClient.invalidateQueries();
        },
        onError: (error) =>
          toast.error(getProblemDetail(error, "Project member role could not be updated.")),
      },
    });

  if (projectQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading project...</p>;
  }
  if (isAxiosError(projectQuery.error) && projectQuery.error.response?.status === 403) {
    return <ForbiddenPage />;
  }
  if (!project) {
    return (
      <PageHeader
        title="Project not found"
        description="The project may have been removed or you do not have access."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={project.name}
        description={project.description ?? "No description."}
        metadata={
          <>
            {team && canViewTeam(currentUser, team.id) ? (
              <Button asChild variant="ghost" size="sm" className="h-7 px-2">
                <Link to={`/teams/${team.id}`}>
                  <Building2 />
                  {team.name}
                </Link>
              </Button>
            ) : team ? (
              <span className="inline-flex h-7 items-center gap-2 px-2 text-sm text-muted-foreground">
                <Building2 />
                {team.name}
              </span>
            ) : null}
            <StatusBadge variant={project.is_active ? "active" : "inactive"}>
              {project.is_active ? "Active" : "Archived"}
            </StatusBadge>
          </>
        }
        actions={
          canManageProject ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Project actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                  <Pencil />
                  Edit project
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setArchiveOpen(true)}
                  disabled={!project.is_active || !canArchiveProject}
                >
                  <Archive />
                  Archive project
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    updateMutation.mutate({
                      projectId: project.id,
                      data: { is_active: true },
                    })
                  }
                  disabled={project.is_active || updateMutation.isPending}
                  className={canArchiveProject ? undefined : "hidden"}
                >
                  <RotateCcw />
                  Reactivate project
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null
        }
      />

      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const next = new URLSearchParams(searchParams);
          if (value === "overview") next.delete("tab");
          else next.set("tab", value);
          setSearchParams(next, { replace: true });
        }}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="keys">
            <KeyRound className="size-3.5" />
            Keys ({keys.length})
          </TabsTrigger>
          <TabsTrigger value="access">Access</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(22rem,0.8fr)]">
            <EntityUsageCard
              usage={usage}
              isLoading={usageQuery.isPending}
              description="Aggregate project usage across all virtual keys, including inherited team policies."
            />
            <Card>
              <CardHeader>
                <CardTitle>Ownership</CardTitle>
                <CardDescription>Application owner context for this project.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <Fact label="Owning team" value={team?.name ?? "Unknown"} />
                <Fact label="Project members" value={`${projectMembers.length}`} />
                <Fact label="Active keys" value={`${keys.filter((key) => key.is_usable).length}`} />
                <Fact label="Status" value={project.is_active ? "Active" : "Archived"} />
              </CardContent>
            </Card>
          </div>
          <ProjectSetupChecklist
            ownershipActive={Boolean(project.is_active && (team?.is_active ?? true))}
            effectiveAccessPolicy={Boolean(effectiveAccess?.access_policy)}
            routableRoute={Boolean(effectiveAccess?.routes.length)}
            keyCreated={keys.length > 0}
            firstRequestObserved={(usage?.totals.requests ?? 0) > 0}
            isLoading={effectiveAccessQuery.isPending || usageQuery.isPending}
          />
          <UsageRecordsDrilldown
            title="Project usage records"
            filters={{ project_id: project.id }}
          />
          <RecentGuardrailEventsCard
            filters={{ project_id: project.id }}
            enabled={canManageProject || hasPermission(currentUser, "guardrails.view")}
          />
        </TabsContent>
        <TabsContent value="keys" className="space-y-4">
          <ProjectKeysSection
            projectId={projectId}
            project={project}
            teamName={team?.name}
            keys={keys}
            isLoading={keysQuery.isPending}
            onView={(keyId) => navigate(`/projects/${projectId}/keys/${keyId}`)}
            canManage={canManageProject}
          />
        </TabsContent>
        <TabsContent value="access" className="space-y-4">
          <ProjectAccessSection
            projectId={projectId}
            teamId={project.team_id}
            canManage={canManageProject}
          />
        </TabsContent>
        <TabsContent value="members" className="space-y-4">
          <MembersCard
            title="Project members"
            description="Members can view project details, keys, usage, and activity. Admins can also edit the project and manage virtual keys."
            orgMembers={orgMembers}
            members={projectMembers}
            roleOptions={[
              { value: "project_admin", label: "Project admin" },
              { value: "project_member", label: "Project member" },
            ]}
            defaultRole="project_member"
            getRole={(member) => member.project_role}
            canManage={canManageProject}
            isLoading={memberOptionsQuery.isPending || projectMembersQuery.isPending}
            isPending={
              addProjectMemberMutation.isPending ||
              removeProjectMemberMutation.isPending ||
              updateProjectMemberMutation.isPending
            }
            onAdd={(userId, role) =>
              addProjectMemberMutation.mutate({
                projectId: project.id,
                data: { user_id: userId, role },
              })
            }
            onRoleChange={(member, role) =>
              updateProjectMemberMutation.mutate({
                projectId: project.id,
                userId: member.user_id,
                data: { role },
              })
            }
            onRemove={(member) =>
              removeProjectMemberMutation.mutate({
                projectId: project.id,
                userId: member.user_id,
              })
            }
            removeAriaLabel={() => "Remove project member"}
            emptyTitle="No project members assigned"
            emptyDescription="Project management currently comes from org or team permissions."
          />
        </TabsContent>
      </Tabs>

      <EditProjectDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        project={project}
        onSubmit={(data) => updateMutation.mutate({ projectId: project.id, data })}
        isPending={updateMutation.isPending}
      />

      <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive project?</DialogTitle>
            <DialogDescription>
              The project will stop accepting new requests. Existing virtual keys remain visible but
              cannot be used.
            </DialogDescription>
          </DialogHeader>
          {archiveImpactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Checking impact...</p>
          ) : archiveImpact ? (
            <div className="space-y-3">
              <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm md:grid-cols-3">
                <Fact label="Active keys" value={`${archiveImpact.active_virtual_key_count}`} />
                <Fact
                  label={`${archiveImpact.recent_usage_window_days}d requests`}
                  value={(archiveImpact.recent_request_count ?? 0).toLocaleString()}
                />
                <Fact
                  label="Estimated spend"
                  value={formatCents(archiveImpact.recent_cost_cents)}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                Effective access: {effectiveAccessPolicyNames(archiveImpact.effective_access)} ·{" "}
                {archiveImpact.effective_access.routes.length} routable routes.
              </p>
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
              disabled={deactivateMutation.isPending || !archiveImpact}
              onClick={() => deactivateMutation.mutate({ projectId: project.id })}
            >
              {deactivateMutation.isPending ? "Archiving..." : "Archive project"}
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

function ProjectSetupChecklist({
  ownershipActive,
  effectiveAccessPolicy,
  routableRoute,
  keyCreated,
  firstRequestObserved,
  isLoading,
}: {
  ownershipActive: boolean;
  effectiveAccessPolicy: boolean;
  routableRoute: boolean;
  keyCreated: boolean;
  firstRequestObserved: boolean;
  isLoading: boolean;
}) {
  const items = [
    ["Ownership active", ownershipActive],
    ["Effective access policy", effectiveAccessPolicy],
    ["Routable provider/model", routableRoute],
    ["Key created", keyCreated],
    ["First request observed", firstRequestObserved],
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Project setup</CardTitle>
        <CardDescription>
          Minimum checks before this application can send gateway traffic.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Checking setup...</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-5">
            {items.map(([label, complete]) => (
              <div key={label} className="rounded-md border bg-muted/20 p-3">
                <StatusBadge variant={complete ? "active" : "muted"}>
                  {complete ? "Ready" : "Missing"}
                </StatusBadge>
                <p className="mt-2 text-sm font-medium">{label}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
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

function formatCents(value: number | null | undefined) {
  return `$${((value ?? 0) / 100).toFixed(2)}`;
}

function effectiveAccessPolicyNames(summary: EffectiveAccessSummary) {
  const policies =
    (
      summary as EffectiveAccessSummary & {
        access_policies?: NonNullable<EffectiveAccessSummary["access_policy"]>[];
      }
    ).access_policies ?? (summary.access_policy ? [summary.access_policy] : []);
  return policies.length
    ? policies.map((policy) => policy.name).join(", ")
    : "No active access policy";
}
