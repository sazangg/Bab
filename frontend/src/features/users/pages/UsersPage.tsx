import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  ChevronDown,
  Copy,
  FilterX,
  RotateCcw,
  Search,
  Trash2,
  UserPlus,
  UserX,
  Users,
} from "lucide-react";
import { Fragment, type ReactNode, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

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
  const [expandedMemberId, setExpandedMemberId] = useState<string | null>(null);

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
        if (response.status === 201 && response.data.invite_url) {
          const inviteUrl = resolveInviteUrl(response.data.invite_url);
          setLatestInviteUrl(inviteUrl);
          await navigator.clipboard?.writeText(inviteUrl);
          toast.success("Invite created. Link is shown below and copied.");
        } else {
          toast.success("Invite created.");
        }
      },
      onError: () => toast.error("Invite could not be created."),
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
      onError: (error) => {
        if (isAxiosError(error) && error.response?.status === 409) {
          toast.error("A user with this email already exists.");
          return;
        }
        toast.error("User could not be created.");
      },
    },
  });
  const updateMemberMutation = useUpdateMemberApiV1AuthMembersUserIdPatch({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Member role updated.");
      },
      onError: () => toast.error("Member role could not be updated."),
    },
  });
  const updateMemberStatusMutation = useUpdateMemberStatusApiV1AuthMembersUserIdStatusPatch({
    mutation: {
      onSuccess: async (_response, variables) => {
        await queryClient.invalidateQueries();
        toast.success(
          variables.data.status === "active" ? "User reactivated." : "User deactivated.",
        );
      },
      onError: () => toast.error("Member status could not be updated."),
    },
  });
  const revokeInviteMutation = useRevokeInviteApiV1AuthInvitesInviteIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        toast.success("Invite revoked.");
      },
      onError: () => toast.error("Invite could not be revoked."),
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
  const createUserDisabled =
    isPending ||
    !canManageOrgMembers ||
    !createEmail.trim() ||
    createPassword.trim().length < 8 ||
    !isWithinBcryptByteLimit(createPassword) ||
    (createProjectId !== NO_SCOPE && createProjectRole === NO_SCOPE);
  const inviteDisabled =
    isPending ||
    !canInvite ||
    !email.trim() ||
    (!canManageOrgMembers && !scopedInviteHasTarget) ||
    (projectId !== NO_SCOPE && projectRole === NO_SCOPE);
  const inviteDisabledReason = !email.trim()
    ? "Enter an email address to create an invite."
    : !canManageOrgMembers && !scopedInviteHasTarget
      ? "Choose one of your managed teams or projects before inviting."
      : projectId !== NO_SCOPE && projectRole === NO_SCOPE
        ? "Choose a project role before inviting."
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
    setEmail("");
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
              <CardContent className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_180px_180px]">
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
                    options={manageableTeams.map((team) => ({ value: team.id, label: team.name }))}
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
                <div className="flex items-end lg:col-start-4">
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
          isPending={isPending}
          search={memberSearch}
          roleFilter={memberRoleFilter}
          statusFilter={memberStatusFilter}
          expandedMemberId={expandedMemberId}
          currentUserId={currentUser?.id}
          currentUserRole={currentUser?.role}
          assignableRoles={assignableOrgRoles}
          teamById={teamById}
          projectById={projectById}
          onSearch={setMemberSearch}
          onRoleFilter={setMemberRoleFilter}
          onStatusFilter={setMemberStatusFilter}
          onToggleExpanded={(memberId) =>
            setExpandedMemberId((current) => (current === memberId ? null : memberId))
          }
          onUpdateRole={(member, nextRole) =>
            updateMemberMutation.mutate({ userId: member.user_id, data: { role: nextRole } })
          }
          onUpdateStatus={(member, status) =>
            updateMemberStatusMutation.mutate({ userId: member.user_id, data: { status } })
          }
        />
      ) : (
        <ScopedAccessCard teams={manageableTeams} projects={manageableProjects} />
      )}

      {canManageOrgMembers ? (
        <InvitesCard
          invites={filteredInvites}
          isLoading={invitesQuery.isPending}
          isPending={isPending}
          statusFilter={inviteStatusFilter}
          teamById={teamById}
          projectById={projectById}
          onStatusFilter={setInviteStatusFilter}
          onRevoke={(invite) => revokeInviteMutation.mutate({ inviteId: invite.id })}
        />
      ) : null}
    </div>
  );
}

function MembersCard({
  members,
  allMembers,
  isLoading,
  isPending,
  search,
  roleFilter,
  statusFilter,
  expandedMemberId,
  currentUserId,
  currentUserRole,
  assignableRoles,
  teamById,
  projectById,
  onSearch,
  onRoleFilter,
  onStatusFilter,
  onToggleExpanded,
  onUpdateRole,
  onUpdateStatus,
}: {
  members: MemberResponse[];
  allMembers: MemberResponse[];
  isLoading: boolean;
  isPending: boolean;
  search: string;
  roleFilter: string;
  statusFilter: string;
  expandedMemberId: string | null;
  currentUserId?: string;
  currentUserRole?: string;
  assignableRoles: string[];
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
  onSearch: (value: string) => void;
  onRoleFilter: (value: string) => void;
  onStatusFilter: (value: string) => void;
  onToggleExpanded: (memberId: string) => void;
  onUpdateRole: (member: MemberResponse, role: string) => void;
  onUpdateStatus: (member: MemberResponse, status: "active" | "inactive") => void;
}) {
  const hasFilters = search || roleFilter !== ALL_ROLES || statusFilter !== ALL_STATUSES;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>Org roles plus team and project access for each account.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              placeholder="Search by email or name"
              className="pl-9"
            />
          </div>
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
          <Button
            type="button"
            variant="outline"
            disabled={!hasFilters}
            onClick={() => {
              onSearch("");
              onRoleFilter(ALL_ROLES);
              onStatusFilter(ALL_STATUSES);
            }}
          >
            <FilterX data-icon="inline-start" />
            Clear
          </Button>
        </div>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading members...</p>
        ) : allMembers.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No members found"
            description="Invite or create the first user to start assigning access."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Org role</TableHead>
                <TableHead>Scoped roles</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => {
                const expanded = expandedMemberId === member.user_id;
                const canChangeRole = canManageMemberRole(
                  currentUserRole,
                  member.role,
                  member.user_id,
                  currentUserId,
                );
                return (
                  <Fragment key={member.user_id}>
                    <TableRow className={member.status !== "active" ? "opacity-60" : undefined}>
                      <TableCell>
                        <button
                          type="button"
                          className="flex min-w-0 items-center gap-2 text-left"
                          onClick={() => onToggleExpanded(member.user_id)}
                        >
                          <ChevronDown
                            className={`size-4 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
                          />
                          <span className="min-w-0">
                            <span className="block truncate font-medium">{member.email}</span>
                            {member.name ? (
                              <span className="block truncate text-xs text-muted-foreground">
                                {member.name}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell>
                        <Badge variant={member.status === "active" ? "secondary" : "outline"}>
                          {member.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {canChangeRole && member.status === "active" ? (
                          <RoleSelect
                            value={member.role}
                            onValueChange={(value) => onUpdateRole(member, value)}
                            roles={assignableRoles.filter((role) =>
                              canAssignRole(currentUserRole, member.role, role),
                            )}
                          />
                        ) : (
                          <Badge variant="outline">{formatOrgRole(member.role)}</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <ScopedBadges
                          member={member}
                          teamById={teamById}
                          projectById={projectById}
                        />
                      </TableCell>
                      <TableCell>{new Date(member.created_at).toLocaleDateString()}</TableCell>
                      <TableCell className="text-right">
                        {canChangeRole && member.status === "active" ? (
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
                        ) : canChangeRole ? (
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
                        ) : null}
                      </TableCell>
                    </TableRow>
                    {expanded ? (
                      <TableRow>
                        <TableCell colSpan={6} className="bg-muted/30">
                          <MemberDetails
                            member={member}
                            teamById={teamById}
                            projectById={projectById}
                          />
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
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
      <CardContent className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_160px_180px_170px_180px_170px]">
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
  isLoading,
  isPending,
  statusFilter,
  teamById,
  projectById,
  onStatusFilter,
  onRevoke,
}: {
  invites: InviteResponse[];
  isLoading: boolean;
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
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading invites...</p>
        ) : invites.length === 0 ? (
          <p className="text-sm text-muted-foreground">No invites match this filter.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Access</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((invite) => (
                <TableRow key={invite.id}>
                  <TableCell>{invite.email}</TableCell>
                  <TableCell>
                    <Badge variant={invite.status === "pending" ? "secondary" : "outline"}>
                      {invite.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <InviteAccess invite={invite} teamById={teamById} projectById={projectById} />
                  </TableCell>
                  <TableCell>{new Date(invite.expires_at).toLocaleDateString()}</TableCell>
                  <TableCell className="text-right">
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
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
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

function MemberDetails({
  member,
  teamById,
  projectById,
}: {
  member: MemberResponse;
  teamById: Record<string, TeamResponse>;
  projectById: Record<string, ProjectResponse>;
}) {
  return (
    <div className="grid gap-4 text-sm lg:grid-cols-3">
      <DetailGroup title="Access source">
        <Badge variant="secondary">{formatOrgRole(member.role)}</Badge>
        {member.team_memberships?.length
          ? member.team_memberships.map((item) => (
              <Badge key={`source-team-${item.team_id}`} variant="outline">
                {teamById[item.team_id]?.name ?? item.team_id}: {formatScopedRole(item.role)}
              </Badge>
            ))
          : null}
        {member.project_memberships?.length
          ? member.project_memberships.map((item) => (
              <Badge key={`source-project-${item.project_id}`} variant="outline">
                {projectById[item.project_id]?.name ?? item.project_id}:{" "}
                {formatScopedRole(item.role)}
              </Badge>
            ))
          : null}
      </DetailGroup>
      <DetailGroup title="Team roles">
        {member.team_memberships?.length ? (
          member.team_memberships.map((item) => (
            <Badge key={item.team_id} variant="outline">
              {teamById[item.team_id]?.name ?? item.team_id}: {formatScopedRole(item.role)}
            </Badge>
          ))
        ) : (
          <span className="text-muted-foreground">No team role</span>
        )}
      </DetailGroup>
      <DetailGroup title="Project roles">
        {member.project_memberships?.length ? (
          member.project_memberships.map((item) => (
            <Badge key={item.project_id} variant="outline">
              {projectById[item.project_id]?.name ?? item.project_id}: {formatScopedRole(item.role)}
            </Badge>
          ))
        ) : (
          <span className="text-muted-foreground">No project role</span>
        )}
      </DetailGroup>
      <DetailGroup title="Capabilities">
        {member.effective_permissions?.length ? (
          member.effective_permissions.slice(0, 12).map((permission) => (
            <Badge key={permission} variant="secondary">
              {permission}
            </Badge>
          ))
        ) : (
          <span className="text-muted-foreground">No derived capabilities</span>
        )}
      </DetailGroup>
    </div>
  );
}

function DetailGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium uppercase text-muted-foreground">{title}</div>
      <div className="flex flex-wrap gap-2">{children}</div>
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
