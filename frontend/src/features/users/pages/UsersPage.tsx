import { useQueryClient } from "@tanstack/react-query";
import { Copy, RotateCcw, Search, Trash2, UserPlus, UserX, Users } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
  isProjectAdmin,
  isTeamAdmin,
} from "@/features/auth/lib/permissions";
import { isWithinBcryptByteLimit } from "@/features/auth/lib/password";
import {
  useCreateInviteApiV1AuthInvitesPost,
  useCreateMemberApiV1AuthMembersPost,
  useListInvitesApiV1AuthInvitesGet,
  useListMembersApiV1AuthMembersGet,
  useMeApiV1AuthMeGet,
  useRevokeInviteApiV1AuthInvitesInviteIdDelete,
  useUpdateMemberApiV1AuthMembersUserIdPatch,
  useUpdateMemberStatusApiV1AuthMembersUserIdStatusPatch,
} from "@/shared/api/generated/auth/auth";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import type {
  AuthenticatedUser,
  InviteResponse,
  MemberResponse,
  ProjectResponse,
  TeamResponse,
} from "@/shared/api/generated/schemas";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { EventDetailSheet, type EventDetailRow } from "@/shared/components/EventDetailSheet";
import { FilterToolbar, type FilterChip } from "@/shared/components/FilterToolbar";
import { PageHeader } from "@/shared/components/PageHeader";
import { getProblemDetail } from "@/shared/api/problem-detail";

const NO_SCOPE = "__none__";
const ALL_STATUSES = "__all_statuses__";
const ALL_ROLES = "__all_roles__";

export function UsersPage() {
  const queryClient = useQueryClient();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageOrgMembers = hasPermission(currentUser, "members.manage");
  const canInvite =
    canManageOrgMembers ||
    hasAnyTeamAdminMembership(currentUser) ||
    hasAnyProjectAdminMembership(currentUser);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("org_member");
  const [teamId, setTeamId] = useState(NO_SCOPE);
  const [teamRole, setTeamRole] = useState(NO_SCOPE);
  const [projectId, setProjectId] = useState(NO_SCOPE);
  const [projectRole, setProjectRole] = useState(NO_SCOPE);
  const [createEmail, setCreateEmail] = useState("");
  const [createName, setCreateName] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState("org_viewer");
  const [createTeamId, setCreateTeamId] = useState(NO_SCOPE);
  const [createTeamRole, setCreateTeamRole] = useState(NO_SCOPE);
  const [createProjectId, setCreateProjectId] = useState(NO_SCOPE);
  const [createProjectRole, setCreateProjectRole] = useState(NO_SCOPE);
  const [latestInviteUrl, setLatestInviteUrl] = useState("");
  const [memberSearch, setMemberSearch] = useState("");
  const [memberRoleFilter, setMemberRoleFilter] = useState(ALL_ROLES);
  const [memberStatusFilter, setMemberStatusFilter] = useState(ALL_STATUSES);
  const [inviteStatusFilter, setInviteStatusFilter] = useState("pending");
  const [memberToDeactivate, setMemberToDeactivate] = useState<MemberResponse | null>(null);
  const [inviteToRevoke, setInviteToRevoke] = useState<InviteResponse | null>(null);

  const membersQuery = useListMembersApiV1AuthMembersGet({
    query: { enabled: canManageOrgMembers },
  });
  const invitesQuery = useListInvitesApiV1AuthInvitesGet({
    query: { enabled: canInvite },
  });
  const teamsQuery = useListTeamsApiV1TeamsGet({ query: { enabled: canInvite } });
  const projectsQuery = useListProjectsApiV1ProjectsGet({ query: { enabled: canInvite } });

  const members = useMemo(
    () => (membersQuery.data?.status === 200 ? membersQuery.data.data : []),
    [membersQuery.data],
  );
  const invites = useMemo(
    () => (invitesQuery.data?.status === 200 ? invitesQuery.data.data : []),
    [invitesQuery.data],
  );
  const teams = useMemo(
    () => (teamsQuery.data?.status === 200 ? teamsQuery.data.data : []),
    [teamsQuery.data],
  );
  const projects = useMemo(
    () => (projectsQuery.data?.status === 200 ? projectsQuery.data.data : []),
    [projectsQuery.data],
  );
  const teamById = useMemo(() => indexById(teams), [teams]);
  const projectById = useMemo(() => indexById(projects), [projects]);
  const manageableTeams = useMemo(
    () => teams.filter((team) => team.is_active && canInviteToTeam(currentUser, team.id)),
    [currentUser, teams],
  );
  const manageableProjects = useMemo(
    () =>
      projects.filter((project) => project.is_active && canInviteToProject(currentUser, project)),
    [currentUser, projects],
  );
  const visibleProjects = useMemo(
    () => manageableProjects.filter((project) => teamId === NO_SCOPE || project.team_id === teamId),
    [manageableProjects, teamId],
  );
  const visibleCreateProjects = useMemo(
    () =>
      manageableProjects.filter(
        (project) => createTeamId === NO_SCOPE || project.team_id === createTeamId,
      ),
    [createTeamId, manageableProjects],
  );
  const assignableOrgRoles = getAssignableOrgRoles(currentUser);
  const filteredMembers = useMemo(
    () =>
      members.filter((member) => {
        const needle = memberSearch.trim().toLowerCase();
        const matchesText =
          !needle ||
          member.email.toLowerCase().includes(needle) ||
          (member.name ?? "").toLowerCase().includes(needle);
        const matchesRole = memberRoleFilter === ALL_ROLES || member.role === memberRoleFilter;
        const matchesStatus =
          memberStatusFilter === ALL_STATUSES || member.status === memberStatusFilter;
        return matchesText && matchesRole && matchesStatus;
      }),
    [memberRoleFilter, memberSearch, memberStatusFilter, members],
  );
  const filteredInvites = useMemo(
    () =>
      invites.filter(
        (invite) => inviteStatusFilter === ALL_STATUSES || invite.status === inviteStatusFilter,
      ),
    [inviteStatusFilter, invites],
  );

  const inviteMutation = useCreateInviteApiV1AuthInvitesPost({
    mutation: {
      onSuccess: async (response) => {
        await queryClient.invalidateQueries();
        setEmail("");
        setRole("org_member");
        setTeamId(NO_SCOPE);
        setTeamRole(NO_SCOPE);
        setProjectId(NO_SCOPE);
        setProjectRole(NO_SCOPE);
        if (response.status === 201 && response.data.invite_url) {
          const inviteUrl = resolveInviteUrl(response.data.invite_url);
          setLatestInviteUrl(inviteUrl);
          await navigator.clipboard?.writeText(inviteUrl);
          toast.success("Invite created. Link is shown below and copied.");
        } else {
          toast.success("Invite created.");
        }
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Invite could not be created.")),
    },
  });
  const createMemberMutation = useCreateMemberApiV1AuthMembersPost({
    mutation: {
      onSuccess: async (response) => {
        await queryClient.invalidateQueries();
        if (response.status === 201) {
          setCreateEmail("");
          setCreateName("");
          setCreatePassword("");
          setCreateRole("org_viewer");
          setCreateTeamId(NO_SCOPE);
          setCreateTeamRole(NO_SCOPE);
          setCreateProjectId(NO_SCOPE);
          setCreateProjectRole(NO_SCOPE);
          toast.success("User created.");
        }
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "User could not be created.")),
    },
  });
  const updateMemberMutation = useUpdateMemberApiV1AuthMembersUserIdPatch({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Member role updated.");
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Member role could not be updated.")),
    },
  });
  const updateMemberStatusMutation = useUpdateMemberStatusApiV1AuthMembersUserIdStatusPatch({
    mutation: {
      onSuccess: async (_response, variables) => {
        setMemberToDeactivate(null);
        await queryClient.invalidateQueries();
        toast.success(
          variables.data.status === "active" ? "User reactivated." : "User deactivated.",
        );
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Member status could not be updated.")),
    },
  });
  const revokeInviteMutation = useRevokeInviteApiV1AuthInvitesInviteIdDelete({
    mutation: {
      onSuccess: async () => {
        setInviteToRevoke(null);
        await queryClient.invalidateQueries();
        toast.success("Invite revoked.");
      },
      onError: (error) =>
        toast.error(getProblemDetail(error, "Invite could not be revoked.")),
    },
  });

  const isPending =
    inviteMutation.isPending ||
    createMemberMutation.isPending ||
    updateMemberMutation.isPending ||
    updateMemberStatusMutation.isPending ||
    revokeInviteMutation.isPending;
  const scopedInviteHasTarget =
    teamId !== NO_SCOPE || (projectId !== NO_SCOPE && projectRole !== NO_SCOPE);
  const createScopeError = scopedGrantError(
    createTeamId,
    createTeamRole,
    createProjectId,
    createProjectRole,
  );
  const inviteScopeError = scopedGrantError(teamId, teamRole, projectId, projectRole);
  const createUserDisabled =
    isPending ||
    !canManageOrgMembers ||
    !createEmail.trim() ||
    createPassword.trim().length < 8 ||
    !isWithinBcryptByteLimit(createPassword) ||
    Boolean(createScopeError);
  const inviteDisabled =
    isPending ||
    !canInvite ||
    !email.trim() ||
    (!canManageOrgMembers && !scopedInviteHasTarget) ||
    Boolean(inviteScopeError);
  const inviteDisabledReason = !email.trim()
    ? "Enter an email address to create an invite."
    : !canManageOrgMembers && !scopedInviteHasTarget
      ? "Choose one of your managed teams or projects before inviting."
      : inviteScopeError
        ? inviteScopeError
        : null;

  function submitInvite() {
    inviteMutation.mutate({
      data: {
        email: email.trim(),
        role,
        team_id: teamId === NO_SCOPE ? null : teamId,
        team_role: teamRole === NO_SCOPE ? null : teamRole,
        project_id: projectId === NO_SCOPE ? null : projectId,
        project_role: projectRole === NO_SCOPE ? null : projectRole,
      },
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Organization members, scoped roles, and onboarding invites."
      />

      {canManageOrgMembers ? (
        <Tabs defaultValue="invite" className="space-y-4">
          <TabsList>
            <TabsTrigger value="invite">Invite user</TabsTrigger>
            <TabsTrigger value="create">Create local user</TabsTrigger>
          </TabsList>
          <TabsContent value="invite">
            <InviteUserCard
              email={email}
              role={role}
              teamId={teamId}
              teamRole={teamRole}
              projectId={projectId}
              projectRole={projectRole}
              manageableTeams={manageableTeams}
              visibleProjects={visibleProjects}
              assignableOrgRoles={assignableOrgRoles}
              latestInviteUrl={latestInviteUrl}
              inviteDisabled={inviteDisabled}
              inviteDisabledReason={inviteDisabledReason}
              onEmail={setEmail}
              onRole={setRole}
              onTeam={(value) => {
                setTeamId(value);
                if (value === NO_SCOPE) setTeamRole(NO_SCOPE);
                if (value !== NO_SCOPE && projectId !== NO_SCOPE) {
                  const project = projectById[projectId];
                  if (project?.team_id !== value) setProjectId(NO_SCOPE);
                }
              }}
              onTeamRole={setTeamRole}
              onProject={(value) => {
                setProjectId(value);
                if (value === NO_SCOPE) setProjectRole(NO_SCOPE);
                if (value !== NO_SCOPE && projectRole === NO_SCOPE) setProjectRole("project_admin");
              }}
              onProjectRole={setProjectRole}
              onSubmit={submitInvite}
            />
          </TabsContent>
          <TabsContent value="create">
            <Card>
              <CardHeader>
                <CardTitle>Create local user</CardTitle>
                <CardDescription>
                  Add an account immediately. You are setting the initial password for this user.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-5">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_220px_220px]">
                  <Field id="users-create-email" label="Email">
                    <Input
                      id="users-create-email"
                      type="email"
                      value={createEmail}
                      onChange={(event) => setCreateEmail(event.target.value)}
                      placeholder="teammate@example.com"
                    />
                  </Field>
                  <Field id="users-create-name" label="Name">
                    <Input
                      id="users-create-name"
                      value={createName}
                      onChange={(event) => setCreateName(event.target.value)}
                      placeholder="Optional"
                    />
                  </Field>
                  <Field id="users-create-password" label="Password">
                    <Input
                      id="users-create-password"
                      type="password"
                      value={createPassword}
                      onChange={(event) => setCreatePassword(event.target.value)}
                      placeholder="8+ characters, 72 bytes max"
                    />
                  </Field>
                  <Field label="Org role">
                    <RoleSelect
                      value={createRole}
                      onValueChange={setCreateRole}
                      roles={assignableOrgRoles}
                    />
                  </Field>
                </div>
                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-3">
                    <p className="text-sm font-medium">Scoped access</p>
                    <p className="text-xs text-muted-foreground">
                      Optional team or project access granted when the user is created.
                    </p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <Field label="Team">
                      <ScopeSelect
                        value={createTeamId}
                        onValueChange={(value) => {
                          setCreateTeamId(value);
                          if (value === NO_SCOPE) setCreateTeamRole(NO_SCOPE);
                          if (value !== NO_SCOPE && createProjectId !== NO_SCOPE) {
                            const project = projectById[createProjectId];
                            if (project?.team_id !== value) setCreateProjectId(NO_SCOPE);
                          }
                        }}
                        placeholder="No team"
                        options={manageableTeams.map((team) => ({
                          value: team.id,
                          label: team.name,
                        }))}
                      />
                    </Field>
                    <Field label="Team role">
                      <ScopeSelect
                        value={createTeamRole}
                        onValueChange={setCreateTeamRole}
                        placeholder="No role"
                        disabled={createTeamId === NO_SCOPE}
                        options={[
                          { value: "team_member", label: "Team member" },
                          { value: "team_admin", label: "Team admin" },
                        ]}
                      />
                    </Field>
                    <Field label="Project">
                      <ScopeSelect
                        value={createProjectId}
                        onValueChange={(value) => {
                          setCreateProjectId(value);
                          if (value === NO_SCOPE) setCreateProjectRole(NO_SCOPE);
                          if (value !== NO_SCOPE && createProjectRole === NO_SCOPE) {
                            setCreateProjectRole("project_admin");
                          }
                        }}
                        placeholder="No project"
                        options={visibleCreateProjects.map((project) => ({
                          value: project.id,
                          label: project.name,
                        }))}
                      />
                    </Field>
                    <Field label="Project role">
                      <ScopeSelect
                        value={createProjectRole}
                        onValueChange={setCreateProjectRole}
                        placeholder="No role"
                        disabled={createProjectId === NO_SCOPE}
                        options={[
                          { value: "project_member", label: "Project member" },
                          { value: "project_admin", label: "Project admin" },
                        ]}
                      />
                    </Field>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">{createScopeError}</p>
                  <Button
                    type="button"
                    disabled={createUserDisabled}
                    onClick={() =>
                      createMemberMutation.mutate({
                        data: {
                          email: createEmail.trim(),
                          name: createName.trim() || null,
                          password: createPassword,
                          role: createRole,
                          team_id: createTeamId === NO_SCOPE ? null : createTeamId,
                          team_role: createTeamRole === NO_SCOPE ? null : createTeamRole,
                          project_id: createProjectId === NO_SCOPE ? null : createProjectId,
                          project_role: createProjectRole === NO_SCOPE ? null : createProjectRole,
                        },
                      })
                    }
                  >
                    <UserPlus data-icon="inline-start" />
                    Create user
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      ) : null}

      {!canManageOrgMembers ? (
        <InviteUserCard
          email={email}
          role={role}
          teamId={teamId}
          teamRole={teamRole}
          projectId={projectId}
          projectRole={projectRole}
          manageableTeams={manageableTeams}
          visibleProjects={visibleProjects}
          assignableOrgRoles={assignableOrgRoles}
          latestInviteUrl={latestInviteUrl}
          inviteDisabled={inviteDisabled}
          inviteDisabledReason={inviteDisabledReason}
          onEmail={setEmail}
          onRole={setRole}
          onTeam={(value) => {
            setTeamId(value);
            if (value === NO_SCOPE) setTeamRole(NO_SCOPE);
            if (value !== NO_SCOPE && projectId !== NO_SCOPE) {
              const project = projectById[projectId];
              if (project?.team_id !== value) setProjectId(NO_SCOPE);
            }
          }}
          onTeamRole={setTeamRole}
          onProject={(value) => {
            setProjectId(value);
            if (value === NO_SCOPE) setProjectRole(NO_SCOPE);
            if (value !== NO_SCOPE && projectRole === NO_SCOPE) setProjectRole("project_admin");
          }}
          onProjectRole={setProjectRole}
          onSubmit={submitInvite}
        />
      ) : null}

      {canManageOrgMembers ? (
        <MembersCard
          members={filteredMembers}
          allMembers={members}
          isLoading={membersQuery.isPending}
          error={membersQuery.isError}
          onRetry={() => membersQuery.refetch()}
          isPending={isPending}
          search={memberSearch}
          roleFilter={memberRoleFilter}
          statusFilter={memberStatusFilter}
          currentUserId={currentUser?.id}
          currentUserRole={currentUser?.role}
          assignableRoles={assignableOrgRoles}
          teamById={teamById}
          projectById={projectById}
          onSearch={setMemberSearch}
          onRoleFilter={setMemberRoleFilter}
          onStatusFilter={setMemberStatusFilter}
          onUpdateRole={(member, nextRole) =>
            updateMemberMutation.mutate({ userId: member.user_id, data: { role: nextRole } })
          }
          onUpdateStatus={(member, status) => {
            if (status === "inactive") {
              setMemberToDeactivate(member);
              return;
            }
            updateMemberStatusMutation.mutate({ userId: member.user_id, data: { status } });
          }}
        />
      ) : (
        <ScopedAccessCard teams={manageableTeams} projects={manageableProjects} />
      )}

      {canManageOrgMembers ? (
        <InvitesCard
          invites={filteredInvites}
          allInvites={invites}
          isLoading={invitesQuery.isPending}
          error={invitesQuery.isError}
          onRetry={() => invitesQuery.refetch()}
          isPending={isPending}
          statusFilter={inviteStatusFilter}
          teamById={teamById}
          projectById={projectById}
          onStatusFilter={setInviteStatusFilter}
          onRevoke={setInviteToRevoke}
        />
      ) : null}
      <DestructiveActionDialog
        open={Boolean(memberToDeactivate)}
        title="Deactivate user?"
        description={
          memberToDeactivate
            ? `Deactivating ${memberToDeactivate.email} blocks their access until reactivated.`
            : ""
        }
        confirmLabel="Deactivate user"
        pending={updateMemberStatusMutation.isPending}
        onOpenChange={(open) => !open && setMemberToDeactivate(null)}
        onConfirm={() => {
          if (memberToDeactivate) {
            updateMemberStatusMutation.mutate({
              userId: memberToDeactivate.user_id,
              data: { status: "inactive" },
            });
          }
        }}
      />
      <DestructiveActionDialog
        open={Boolean(inviteToRevoke)}
        title="Revoke invite?"
        description={
          inviteToRevoke
            ? `Revoking the invite for ${inviteToRevoke.email} invalidates its pending link.`
            : ""
        }
        confirmLabel="Revoke invite"
        pending={revokeInviteMutation.isPending}
        onOpenChange={(open) => !open && setInviteToRevoke(null)}
        onConfirm={() => {
          if (inviteToRevoke) {
            revokeInviteMutation.mutate({ inviteId: inviteToRevoke.id });
          }
        }}
      />
    </div>
  );
}

function MembersCard({
  members,
  allMembers,
  isLoading,
  error,
  onRetry,
  isPending,
  search,
  roleFilter,
  statusFilter,
  currentUserId,
  currentUserRole,
  assignableRoles,
  teamById,
  projectById,
  onSearch,
  onRoleFilter,
  onStatusFilter,
  onUpdateRole,
  onUpdateStatus,
}: {
  members: MemberResponse[];
  allMembers: MemberResponse[];
  isLoading: boolean;
  error: boolean;
  onRetry: () => void;
  isPending: boolean;
  search: string;
  roleFilter: string;
  statusFilter: string;
  currentUserId?: string;
  currentUserRole?: string;
  assignableRoles: string[];
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
  onSearch: (value: string) => void;
  onRoleFilter: (value: string) => void;
  onStatusFilter: (value: string) => void;
  onUpdateRole: (member: MemberResponse, role: string) => void;
  onUpdateStatus: (member: MemberResponse, status: "active" | "inactive") => void;
}) {
  const [selected, setSelected] = useState<MemberResponse | null>(null);

  const chips: FilterChip[] = [];
  if (search.trim()) {
    chips.push({ key: "q", label: `Search: ${search.trim()}`, onRemove: () => onSearch("") });
  }
  if (roleFilter !== ALL_ROLES) {
    chips.push({
      key: "role",
      label: `Role: ${formatOrgRole(roleFilter)}`,
      onRemove: () => onRoleFilter(ALL_ROLES),
    });
  }
  if (statusFilter !== ALL_STATUSES) {
    chips.push({
      key: "status",
      label: `Status: ${statusFilter}`,
      onRemove: () => onStatusFilter(ALL_STATUSES),
    });
  }
  const clearAll = () => {
    onSearch("");
    onRoleFilter(ALL_ROLES);
    onStatusFilter(ALL_STATUSES);
  };

  const columns: DataTableColumn<MemberResponse>[] = [
    {
      key: "user",
      header: "User",
      cell: (member) => (
        <>
          <div className="font-medium">{member.email}</div>
          {member.name ? <div className="text-xs text-muted-foreground">{member.name}</div> : null}
        </>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (member) => (
        <Badge variant={member.status === "active" ? "secondary" : "outline"}>
          {member.status}
        </Badge>
      ),
    },
    {
      key: "org_role",
      header: "Org role",
      cell: (member) => {
        const canChangeRole = canManageMemberRole(
          currentUserRole,
          member.role,
          member.user_id,
          currentUserId,
        );
        return canChangeRole && member.status === "active" ? (
          <div onClick={(event) => event.stopPropagation()}>
            <RoleSelect
              value={member.role}
              onValueChange={(value) => onUpdateRole(member, value)}
              roles={assignableRoles.filter((role) =>
                canAssignRole(currentUserRole, member.role, role),
              )}
            />
          </div>
        ) : (
          <Badge variant="outline">{formatOrgRole(member.role)}</Badge>
        );
      },
    },
    {
      key: "scoped",
      header: "Scoped roles",
      cell: (member) => (
        <ScopedBadges member={member} teamById={teamById} projectById={projectById} />
      ),
    },
    {
      key: "joined",
      header: "Joined",
      cell: (member) => new Date(member.created_at).toLocaleDateString(),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (member) => {
        const canChangeRole = canManageMemberRole(
          currentUserRole,
          member.role,
          member.user_id,
          currentUserId,
        );
        if (!canChangeRole) return null;
        return (
          <div onClick={(event) => event.stopPropagation()}>
            {member.status === "active" ? (
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                disabled={isPending}
                onClick={() => onUpdateStatus(member, "inactive")}
                aria-label="Deactivate user"
              >
                <UserX />
              </Button>
            ) : (
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                disabled={isPending}
                onClick={() => onUpdateStatus(member, "active")}
                aria-label="Reactivate user"
              >
                <RotateCcw />
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  const detailRows: EventDetailRow[] = selected
    ? [
        {
          label: "Status",
          value: (
            <Badge variant={selected.status === "active" ? "secondary" : "outline"}>
              {selected.status}
            </Badge>
          ),
        },
        { label: "Org role", value: <Badge variant="outline">{formatOrgRole(selected.role)}</Badge> },
        { label: "Joined", value: new Date(selected.created_at).toLocaleString() },
        {
          label: "Team roles",
          value: selected.team_memberships?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {selected.team_memberships.map((item) => (
                <Badge key={item.team_id} variant="outline">
                  {teamById[item.team_id]?.name ?? item.team_id}: {formatScopedRole(item.role)}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-muted-foreground">No team role</span>
          ),
        },
        {
          label: "Project roles",
          value: selected.project_memberships?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {selected.project_memberships.map((item) => (
                <Badge key={item.project_id} variant="outline">
                  {projectById[item.project_id]?.name ?? item.project_id}:{" "}
                  {formatScopedRole(item.role)}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-muted-foreground">No project role</span>
          ),
        },
        {
          label: "Capabilities",
          value: selected.effective_permissions?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {selected.effective_permissions.slice(0, 12).map((permission) => (
                <Badge key={permission} variant="secondary">
                  {permission}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-muted-foreground">No derived capabilities</span>
          ),
        },
      ]
    : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>Org roles plus team and project access for each account.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FilterToolbar chips={chips} onClearAll={chips.length > 0 ? clearAll : undefined}>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              placeholder="Search by email or name"
              className="pl-9"
            />
          </div>
          <div className="w-44">
            <ScopeSelect
              value={roleFilter}
              onValueChange={onRoleFilter}
              placeholder="All roles"
              includeNone={false}
              options={[
                { value: ALL_ROLES, label: "All roles" },
                { value: "org_owner", label: "Org owner" },
                { value: "org_admin", label: "Org admin" },
                { value: "org_viewer", label: "Org viewer" },
                { value: "org_member", label: "Org member" },
              ]}
            />
          </div>
          <div className="w-40">
            <ScopeSelect
              value={statusFilter}
              onValueChange={onStatusFilter}
              placeholder="All statuses"
              includeNone={false}
              options={[
                { value: ALL_STATUSES, label: "All statuses" },
                { value: "active", label: "Active" },
                { value: "inactive", label: "Inactive" },
              ]}
            />
          </div>
        </FilterToolbar>
        <DataTable
          columns={columns}
          data={members}
          loading={isLoading}
          error={error ? "Members could not be loaded." : undefined}
          onRetry={onRetry}
          getRowKey={(member) => member.user_id}
          onRowClick={setSelected}
          rowClassName={(member) => (member.status !== "active" ? "opacity-60" : undefined)}
          empty={
            allMembers.length === 0
              ? {
                  icon: Users,
                  title: "No members found",
                  description: "Invite or create the first user to start assigning access.",
                }
              : {
                  icon: Users,
                  title: "No members match",
                  description: "Try a different search, role, or status.",
                }
          }
        />
      </CardContent>
      <EventDetailSheet
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
        title={selected?.email ?? "Member"}
        description="Org role, scoped team and project roles, and derived capabilities."
        rows={detailRows}
      />
    </Card>
  );
}

function InviteUserCard({
  email,
  role,
  teamId,
  teamRole,
  projectId,
  projectRole,
  manageableTeams,
  visibleProjects,
  assignableOrgRoles,
  latestInviteUrl,
  inviteDisabled,
  inviteDisabledReason,
  onEmail,
  onRole,
  onTeam,
  onTeamRole,
  onProject,
  onProjectRole,
  onSubmit,
}: {
  email: string;
  role: string;
  teamId: string;
  teamRole: string;
  projectId: string;
  projectRole: string;
  manageableTeams: TeamResponse[];
  visibleProjects: ProjectResponse[];
  assignableOrgRoles: string[];
  latestInviteUrl: string;
  inviteDisabled: boolean;
  inviteDisabledReason: string | null;
  onEmail: (value: string) => void;
  onRole: (value: string) => void;
  onTeam: (value: string) => void;
  onTeamRole: (value: string) => void;
  onProject: (value: string) => void;
  onProjectRole: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Invite user</CardTitle>
        <CardDescription>
          Send a link so the recipient can create their own password and join with the selected
          access.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <Field id="users-invite-email" label="Email">
            <Input
              id="users-invite-email"
              type="email"
              value={email}
              onChange={(event) => onEmail(event.target.value)}
              placeholder="teammate@example.com"
            />
          </Field>
          <Field label="Org role">
            <RoleSelect value={role} onValueChange={onRole} roles={assignableOrgRoles} />
          </Field>
        </div>
        <div className="rounded-md border bg-muted/20 p-3">
          <div className="mb-3">
            <p className="text-sm font-medium">Scoped access</p>
            <p className="text-xs text-muted-foreground">
              Optional team or project role included with this invite.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Field label="Team">
              <ScopeSelect
                value={teamId}
                onValueChange={onTeam}
                placeholder="No team"
                options={manageableTeams.map((team) => ({ value: team.id, label: team.name }))}
              />
            </Field>
            <Field label="Team role">
              <ScopeSelect
                value={teamRole}
                onValueChange={onTeamRole}
                placeholder="No role"
                disabled={teamId === NO_SCOPE}
                options={[
                  { value: "team_member", label: "Team member" },
                  { value: "team_admin", label: "Team admin" },
                ]}
              />
            </Field>
            <Field label="Project">
              <ScopeSelect
                value={projectId}
                onValueChange={onProject}
                placeholder="No project"
                options={visibleProjects.map((project) => ({
                  value: project.id,
                  label: project.name,
                }))}
              />
            </Field>
            <Field label="Project role">
              <ScopeSelect
                value={projectRole}
                onValueChange={onProjectRole}
                placeholder="No role"
                disabled={projectId === NO_SCOPE}
                options={[
                  { value: "project_member", label: "Project member" },
                  { value: "project_admin", label: "Project admin" },
                ]}
              />
            </Field>
          </div>
        </div>
      </CardContent>
      <CardContent className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">
          {inviteDisabledReason ?? "The invite link will be shown here and copied after creation."}
        </p>
        <Button type="button" disabled={inviteDisabled} onClick={onSubmit}>
          <UserPlus data-icon="inline-start" />
          Invite user
        </Button>
      </CardContent>
      {latestInviteUrl ? (
        <CardContent className="border-t pt-4">
          <div className="grid gap-2">
            <Label>Latest invite link</Label>
            <div className="flex gap-2">
              <Input readOnly value={latestInviteUrl} className="font-mono text-xs" />
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  void navigator.clipboard?.writeText(latestInviteUrl);
                  toast.success("Invite link copied.");
                }}
              >
                <Copy data-icon="inline-start" />
                Copy
              </Button>
            </div>
          </div>
        </CardContent>
      ) : null}
    </Card>
  );
}

function InvitesCard({
  invites,
  allInvites,
  isLoading,
  error,
  onRetry,
  isPending,
  statusFilter,
  teamById,
  projectById,
  onStatusFilter,
  onRevoke,
}: {
  invites: InviteResponse[];
  allInvites: InviteResponse[];
  isLoading: boolean;
  error: boolean;
  onRetry: () => void;
  isPending: boolean;
  statusFilter: string;
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
  onStatusFilter: (value: string) => void;
  onRevoke: (invite: InviteResponse) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Invites</CardTitle>
        <CardDescription>
          Pending invite links are shown when the token is available.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="max-w-48">
          <ScopeSelect
            value={statusFilter}
            onValueChange={onStatusFilter}
            placeholder="Status"
            includeNone={false}
            options={[
              { value: ALL_STATUSES, label: "All statuses" },
              { value: "pending", label: "Pending" },
              { value: "accepted", label: "Accepted" },
              { value: "revoked", label: "Revoked" },
              { value: "expired", label: "Expired" },
            ]}
          />
        </div>
        <DataTable
          columns={[
            { key: "email", header: "Email", cell: (invite) => invite.email },
            {
              key: "status",
              header: "Status",
              cell: (invite) => (
                <Badge variant={invite.status === "pending" ? "secondary" : "outline"}>
                  {invite.status}
                </Badge>
              ),
            },
            {
              key: "access",
              header: "Access",
              cell: (invite) => (
                <InviteAccess invite={invite} teamById={teamById} projectById={projectById} />
              ),
            },
            {
              key: "expires",
              header: "Expires",
              cell: (invite) => new Date(invite.expires_at).toLocaleDateString(),
            },
            {
              key: "actions",
              header: "Actions",
              align: "right",
              cell: (invite) => (
                <div className="flex justify-end gap-2">
                  {invite.invite_url ? (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="outline"
                      onClick={() => {
                        void navigator.clipboard?.writeText(invite.invite_url ?? "");
                        toast.success("Invite link copied.");
                      }}
                      aria-label="Copy invite link"
                    >
                      <Copy />
                    </Button>
                  ) : null}
                  {invite.status === "pending" ? (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      disabled={isPending}
                      onClick={() => onRevoke(invite)}
                      aria-label="Revoke invite"
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              ),
            },
          ]}
          data={invites}
          loading={isLoading}
          error={error ? "Invites could not be loaded." : undefined}
          onRetry={onRetry}
          getRowKey={(invite) => invite.id}
          empty={
            allInvites.length === 0
              ? {
                  title: "No invites yet",
                  description: "New pending invites will appear here.",
                }
              : {
                  title: "No invites match",
                  description: "Try a different invite status.",
                }
          }
        />
      </CardContent>
    </Card>
  );
}

function ScopedAccessCard({
  teams,
  projects,
}: {
  teams: TeamResponse[];
  projects: ProjectResponse[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scoped access</CardTitle>
        <CardDescription>Your account can invite only inside these managed scopes.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <ScopeSummary title="Teams" items={teams.map((team) => team.name)} />
        <ScopeSummary title="Projects" items={projects.map((project) => project.name)} />
      </CardContent>
    </Card>
  );
}

function ScopeSummary({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border p-4">
      <div className="mb-3 text-sm font-medium">{title}</div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">None</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <Badge key={item} variant="outline">
              {item}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ScopedBadges({
  member,
  teamById,
  projectById,
}: {
  member: MemberResponse;
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
}) {
  const badges = [
    ...(member.team_memberships ?? []).map((item) => ({
      key: `team-${item.team_id}`,
      label: `${teamById[item.team_id]?.name ?? "Team"} ${formatScopedRole(item.role)}`,
    })),
    ...(member.project_memberships ?? []).map((item) => ({
      key: `project-${item.project_id}`,
      label: `${projectById[item.project_id]?.name ?? "Project"} ${formatScopedRole(item.role)}`,
    })),
  ];
  if (badges.length === 0) return <span className="text-sm text-muted-foreground">None</span>;
  return (
    <div className="flex max-w-sm flex-wrap gap-1.5">
      {badges.slice(0, 3).map((badge) => (
        <Badge key={badge.key} variant="outline">
          {badge.label}
        </Badge>
      ))}
      {badges.length > 3 ? <Badge variant="secondary">+{badges.length - 3}</Badge> : null}
    </div>
  );
}

function DestructiveActionDialog({
  open,
  title,
  description,
  confirmLabel,
  pending,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={pending} onClick={onConfirm}>
            {pending ? "Working..." : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function scopedGrantError(
  teamId: string,
  teamRole: string,
  projectId: string,
  projectRole: string,
) {
  if (projectId !== NO_SCOPE && projectRole === NO_SCOPE) {
    return "Choose a project role before submitting.";
  }
  if (teamId !== NO_SCOPE && projectId === NO_SCOPE && teamRole === NO_SCOPE) {
    return "Choose a team role before submitting.";
  }
  return null;
}

function InviteAccess({
  invite,
  teamById,
  projectById,
}: {
  invite: InviteResponse;
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <Badge variant="outline">{formatOrgRole(invite.role)}</Badge>
      {invite.team_id ? (
        <Badge variant="outline">
          {teamById[invite.team_id]?.name ?? "Team"} {formatScopedRole(invite.team_role ?? "")}
        </Badge>
      ) : null}
      {invite.project_id ? (
        <Badge variant="outline">
          {projectById[invite.project_id]?.name ?? "Project"}{" "}
          {formatScopedRole(invite.project_role ?? "")}
        </Badge>
      ) : null}
    </div>
  );
}

function Field({ id, label, children }: { id?: string; label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

function RoleSelect({
  value,
  onValueChange,
  roles,
}: {
  value: string;
  onValueChange: (value: string) => void;
  roles: string[];
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {roles.map((role) => (
          <SelectItem key={role} value={role}>
            {formatOrgRole(role)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ScopeSelect({
  value,
  onValueChange,
  options,
  placeholder,
  disabled = false,
  includeNone = true,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  disabled?: boolean;
  includeNone?: boolean;
}) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {includeNone ? <SelectItem value={NO_SCOPE}>{placeholder}</SelectItem> : null}
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function indexById<T extends { id: string }>(items: T[]) {
  return items.reduce<Record<string, T>>((acc, item) => {
    acc[item.id] = item;
    return acc;
  }, {});
}

function getAssignableOrgRoles(user: { role?: string; permissions?: string[] } | null) {
  if (user?.role === "org_owner" || user?.permissions?.includes("*")) {
    return ["org_owner", "org_admin", "org_viewer", "org_member"];
  }
  if (user?.role === "org_admin") return ["org_viewer", "org_member"];
  return ["org_member"];
}

function canManageMemberRole(
  actorRole: string | undefined,
  targetRole: string,
  targetUserId: string,
  actorUserId?: string,
) {
  if (!actorRole) return false;
  if (targetUserId === actorUserId) return false;
  if (actorRole === "org_owner") return true;
  if (actorRole === "org_admin") return targetRole === "org_viewer" || targetRole === "org_member";
  return false;
}

function canAssignRole(actorRole: string | undefined, currentRole: string, nextRole: string) {
  if (actorRole === "org_owner") return true;
  if (actorRole === "org_admin") {
    return (
      currentRole !== "org_owner" &&
      currentRole !== "org_admin" &&
      nextRole !== "org_owner" &&
      nextRole !== "org_admin"
    );
  }
  return false;
}

function canInviteToTeam(user: AuthenticatedUser | null | undefined, teamId: string) {
  return hasPermission(user, "members.manage") || isTeamAdmin(user, teamId);
}

function canInviteToProject(user: AuthenticatedUser | null | undefined, project: ProjectResponse) {
  return (
    hasPermission(user, "members.manage") ||
    isTeamAdmin(user, project.team_id) ||
    isProjectAdmin(user, project.id)
  );
}

function formatOrgRole(value: string) {
  if (value === "org_owner") return "Org owner";
  if (value === "org_admin") return "Org admin";
  if (value === "org_member") return "Org member";
  return "Org viewer";
}

function formatScopedRole(value: string) {
  if (value === "team_admin") return "Team admin";
  if (value === "project_admin") return "Project admin";
  if (value === "project_member") return "Project member";
  if (value === "team_member") return "Team member";
  return value || "Role";
}

function resolveInviteUrl(inviteUrl: string) {
  if (/^https?:\/\//i.test(inviteUrl)) return inviteUrl;
  return new URL(inviteUrl, window.location.origin).toString();
}
