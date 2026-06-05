import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  Archive,
  Building2,
  KeyRound,
  MoreHorizontal,
  Pencil,
  RotateCcw,
  Trash2,
  UserPlus,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useDeactivateProjectApiV1ProjectsProjectIdDelete,
  useGetProjectApiV1ProjectsProjectIdGet,
  useGetProjectUsageApiV1ProjectsProjectIdUsageGet,
  useAddProjectMemberApiV1ProjectsProjectIdMembersPost,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useListProjectMembersApiV1ProjectsProjectIdMembersGet,
  useRemoveProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete,
  useUpdateProjectApiV1ProjectsProjectIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListMembersApiV1AuthMembersGet, useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { ProjectAccessSection } from "@/features/projects/sections/ProjectAccessSection";
import { ProjectKeysSection } from "@/features/projects/sections/ProjectKeysSection";
import { EditProjectDialog } from "@/features/projects/components/EditProjectDialog";
import { EntityUsageCard } from "@/features/usage/components/EntityUsageCard";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";
import { hasPermission, isProjectAdmin, isTeamAdmin } from "@/features/auth/lib/permissions";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";
import { RecentGuardrailEventsCard } from "@/features/guardrails/components/RecentGuardrailEventsCard";
import type { MemberResponse, ProjectMemberResponse } from "@/shared/api/generated/schemas";

export function ProjectDetailPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [selectedProjectAdminId, setSelectedProjectAdminId] = useState("");

  const projectQuery = useGetProjectApiV1ProjectsProjectIdGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const orgMembersQuery = useListMembersApiV1AuthMembersGet();
  const projectMembersQuery = useListProjectMembersApiV1ProjectsProjectIdMembersGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const keysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });
  const usageQuery = useGetProjectUsageApiV1ProjectsProjectIdUsageGet(projectId, {
    query: { enabled: Boolean(projectId) },
  });

  const project = projectQuery.data?.status === 200 ? projectQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const orgMembers = orgMembersQuery.data?.status === 200 ? orgMembersQuery.data.data : [];
  const projectMembers =
    projectMembersQuery.data?.status === 200 ? projectMembersQuery.data.data : [];
  const team = project ? teams.find((item) => item.id === project.team_id) : undefined;
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const canManageProject = project
    ? hasPermission(currentUser, "projects.manage") ||
      isTeamAdmin(currentUser, project.team_id) ||
      isProjectAdmin(currentUser, project.id)
    : false;
  const canArchiveProject = project
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
  const addProjectMemberMutation = useAddProjectMemberApiV1ProjectsProjectIdMembersPost({
    mutation: {
      onSuccess: async () => {
        setSelectedProjectAdminId("");
        await queryClient.invalidateQueries();
      },
    },
  });
  const removeProjectMemberMutation =
    useRemoveProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete({
      mutation: {
        onSuccess: async () => {
          await queryClient.invalidateQueries();
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

      <EntityUsageCard
        usage={usage}
        isLoading={usageQuery.isPending}
        description="Aggregate project usage across all virtual keys, including inherited team policies."
      />
      <UsageRecordsDrilldown title="Project usage records" filters={{ project_id: project.id }} />
      <RecentGuardrailEventsCard filters={{ project_id: project.id }} />

      <Tabs defaultValue="keys" className="space-y-4">
        <TabsList>
          <TabsTrigger value="keys">
            <KeyRound className="size-3.5" />
            Keys ({keys.length})
          </TabsTrigger>
          <TabsTrigger value="access">Policies</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
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
          <ProjectAccessSection
            projectId={projectId}
            teamId={project.team_id}
            canManage={canManageProject}
          />
        </TabsContent>
        <TabsContent value="members" className="space-y-4">
          <ProjectAdminsCard
            orgMembers={orgMembers}
            projectMembers={projectMembers}
            selectedUserId={selectedProjectAdminId}
            onSelectedUserChange={setSelectedProjectAdminId}
            canManage={canManageProject}
            isLoading={projectMembersQuery.isPending}
            isPending={addProjectMemberMutation.isPending || removeProjectMemberMutation.isPending}
            onAdd={(userId) =>
              addProjectMemberMutation.mutate({
                projectId: project.id,
                data: { user_id: userId, role: "project_admin" },
              })
            }
            onRemove={(member) =>
              removeProjectMemberMutation.mutate({
                projectId: project.id,
                userId: member.user_id,
              })
            }
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

function ProjectAdminsCard({
  orgMembers,
  projectMembers,
  selectedUserId,
  onSelectedUserChange,
  canManage,
  isLoading,
  isPending,
  onAdd,
  onRemove,
}: {
  orgMembers: MemberResponse[];
  projectMembers: ProjectMemberResponse[];
  selectedUserId: string;
  onSelectedUserChange: (userId: string) => void;
  canManage: boolean;
  isLoading: boolean;
  isPending: boolean;
  onAdd: (userId: string) => void;
  onRemove: (member: ProjectMemberResponse) => void;
}) {
  const assignedIds = new Set(projectMembers.map((member) => member.user_id));
  const assignableMembers = orgMembers.filter(
    (member) => member.status === "active" && !assignedIds.has(member.user_id),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Project admins</CardTitle>
        <CardDescription>
          Project admins can edit this project and manage its virtual keys without gaining
          team-wide access.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {canManage ? (
          <div className="grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="flex flex-col gap-1.5">
              <Label>User</Label>
              <Select value={selectedUserId} onValueChange={onSelectedUserChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select organization member" />
                </SelectTrigger>
                <SelectContent>
                  {assignableMembers.length === 0 ? (
                    <SelectItem value="none" disabled>
                      No available members
                    </SelectItem>
                  ) : (
                    assignableMembers.map((member) => (
                      <SelectItem key={member.user_id} value={member.user_id}>
                        {member.email}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                type="button"
                disabled={isPending || !selectedUserId || selectedUserId === "none"}
                onClick={() => onAdd(selectedUserId)}
              >
                <UserPlus />
                Add admin
              </Button>
            </div>
          </div>
        ) : null}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading project admins...</p>
        ) : projectMembers.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center">
            <p className="text-sm font-medium">No project admins assigned</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Project management currently comes from org or team permissions.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Org role</TableHead>
                  <TableHead>Project role</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projectMembers.map((member) => (
                  <TableRow key={member.user_id}>
                    <TableCell>
                      <div className="font-medium">{member.email}</div>
                      {member.name ? (
                        <div className="text-xs text-muted-foreground">{member.name}</div>
                      ) : null}
                    </TableCell>
                    <TableCell>{formatOrgRole(member.org_role)}</TableCell>
                    <TableCell>Project admin</TableCell>
                    <TableCell>{new Date(member.created_at).toLocaleDateString()}</TableCell>
                    <TableCell className="text-right">
                      {canManage ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          disabled={isPending}
                          onClick={() => onRemove(member)}
                          aria-label="Remove project admin"
                        >
                          <Trash2 />
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatOrgRole(value: string) {
  if (value === "org_owner") return "Owner";
  if (value === "org_admin") return "Admin";
  if (value === "org_viewer") return "Viewer";
  if (value === "org_member") return "Member";
  return value;
}
