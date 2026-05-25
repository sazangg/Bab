import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Archive, Building2, KeyRound, MoreHorizontal, Pencil, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useDeactivateProjectApiV1ProjectsProjectIdDelete,
  useGetProjectApiV1ProjectsProjectIdGet,
  useGetProjectUsageApiV1ProjectsProjectIdUsageGet,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { ProjectAccessSection } from "@/features/projects/sections/ProjectAccessSection";
import { ProjectKeysSection } from "@/features/projects/sections/ProjectKeysSection";
import { EditProjectDialog } from "@/features/projects/components/EditProjectDialog";
import { EntityUsageCard } from "@/features/usage/components/EntityUsageCard";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";
import { hasPermission, isTeamAdmin } from "@/features/auth/lib/permissions";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";

export function ProjectDetailPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const projectQuery = useGetProjectApiV1ProjectsProjectIdGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const keysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const usageQuery = useGetProjectUsageApiV1ProjectsProjectIdUsageGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });

  const project = projectQuery.data?.status === 200 ? projectQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const team = project ? teams.find((item) => item.id === project.team_id) : undefined;
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const canManageProject = project
    ? hasPermission(currentUser, "projects.manage") || isTeamAdmin(currentUser, project.team_id)
    : false;

  const updateMutation = useUpdateProjectApiV1ProjectsProjectIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditOpen(false);
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateMutation = useDeactivateProjectApiV1ProjectsProjectIdDelete({
    mutation: {
      onSuccess: async () => {
        setArchiveOpen(false);
        await queryClient.invalidateQueries();
        navigate("/projects");
      },
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
            {team ? (
              <Button asChild variant="ghost" size="sm" className="h-7 px-2">
                <Link to={`/teams/${team.id}`}>
                  <Building2 />
                  {team.name}
                </Link>
              </Button>
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
                  disabled={!project.is_active}
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
                >
                  <RotateCcw />
                  Reactivate project
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null
        }
      />

      <EntityUsageCard
        usage={usage}
        isLoading={usageQuery.isPending}
        description="Aggregate project usage across all virtual keys, including inherited team allocations."
      />
      <UsageRecordsDrilldown title="Project usage records" filters={{ project_id: project.id }} />

      <Tabs defaultValue="keys" className="space-y-4">
        <TabsList>
          <TabsTrigger value="keys">
            <KeyRound className="size-3.5" />
            Keys ({keys.length})
          </TabsTrigger>
          <TabsTrigger value="access">Allocations</TabsTrigger>
        </TabsList>
        <TabsContent value="keys" className="space-y-4">
          <ProjectKeysSection
            projectId={projectId}
            project={project}
            keys={keys}
            isLoading={keysQuery.isPending}
            onView={(keyId) => navigate(`/projects/${projectId}/keys/${keyId}`)}
            canManage={canManageProject}
          />
        </TabsContent>
        <TabsContent value="access" className="space-y-4">
          <ProjectAccessSection projectId={projectId} teamId={project.team_id} />
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
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={deactivateMutation.isPending}
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
