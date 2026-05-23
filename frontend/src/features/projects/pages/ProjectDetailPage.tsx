import { useQueryClient } from "@tanstack/react-query";
import { Archive, Building2, KeyRound, MoreHorizontal, Pencil, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useDeactivateProjectApiV1ProjectsProjectIdDelete,
  useListProjectsApiV1ProjectsGet,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
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

export function ProjectDetailPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const keysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });

  const project =
    projectsQuery.data?.status === 200
      ? projectsQuery.data.data.find((p) => p.id === projectId)
      : undefined;
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const team = project ? teams.find((item) => item.id === project.team_id) : undefined;
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];

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

  if (projectsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading project...</p>;
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
        actions={
          <>
            {team ? (
              <Button asChild variant="ghost" size="sm">
                <Link to={`/teams/${team.id}`}>
                  <Building2 />
                  {team.name}
                </Link>
              </Button>
            ) : null}
            <StatusBadge variant={project.is_active ? "active" : "inactive"}>
              {project.is_active ? "Active" : "Archived"}
            </StatusBadge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Project actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                  <Pencil className="mr-2 size-4" />
                  Edit project
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setArchiveOpen(true)}
                  disabled={!project.is_active}
                >
                  <Archive className="mr-2 size-4" />
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
                  <RotateCcw className="mr-2 size-4" />
                  Reactivate project
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

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
