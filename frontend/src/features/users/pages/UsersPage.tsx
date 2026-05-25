import { useQueryClient } from "@tanstack/react-query";
import { Copy, RotateCcw, Trash2, UserPlus, UserX, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import {
  useCreateInviteApiV1AuthInvitesPost,
  useCreateMemberApiV1AuthMembersPost,
  useListInvitesApiV1AuthInvitesGet,
  useListMembersApiV1AuthMembersGet,
  useRevokeInviteApiV1AuthInvitesInviteIdDelete,
  useUpdateMemberApiV1AuthMembersUserIdPatch,
  useUpdateMemberStatusApiV1AuthMembersUserIdStatusPatch,
} from "@/shared/api/generated/auth/auth";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

export function UsersPage() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("org_viewer");
  const [createEmail, setCreateEmail] = useState("");
  const [createName, setCreateName] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState("org_viewer");
  const membersQuery = useListMembersApiV1AuthMembersGet();
  const invitesQuery = useListInvitesApiV1AuthInvitesGet();
  const members = membersQuery.data?.status === 200 ? membersQuery.data.data : [];
  const invites = invitesQuery.data?.status === 200 ? invitesQuery.data.data : [];
  const pendingInvites = invites.filter((invite) => invite.status === "pending");
  const inviteMutation = useCreateInviteApiV1AuthInvitesPost({
    mutation: {
      onSuccess: async (response) => {
        await queryClient.invalidateQueries();
        if (response.status === 201 && response.data.invite_url) {
          await navigator.clipboard?.writeText(response.data.invite_url);
          toast.success("Invite created and link copied.");
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
          toast.success("User created.");
        }
      },
      onError: () => toast.error("User could not be created."),
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

  const createUserDisabled = isPending || !createEmail.trim() || createPassword.trim().length < 8;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Organization members, scoped roles, and onboarding invites."
        actions={
          <Button
            disabled={isPending || !email.trim()}
            onClick={() => {
              inviteMutation.mutate({ data: { email: email.trim(), role } });
              setEmail("");
            }}
          >
            <UserPlus data-icon="inline-start" />
            Invite user
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Create local user</CardTitle>
          <CardDescription>
            Add a testable local account immediately and assign its organization role.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_180px_180px_auto]">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="users-create-email">Email</Label>
            <Input
              id="users-create-email"
              type="email"
              value={createEmail}
              onChange={(event) => setCreateEmail(event.target.value)}
              placeholder="teammate@example.com"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="users-create-name">Name</Label>
            <Input
              id="users-create-name"
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="users-create-password">Password</Label>
            <Input
              id="users-create-password"
              type="password"
              value={createPassword}
              onChange={(event) => setCreatePassword(event.target.value)}
              placeholder="8+ characters"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Org role</Label>
            <Select value={createRole} onValueChange={setCreateRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="org_owner">Owner</SelectItem>
                <SelectItem value="org_admin">Admin</SelectItem>
                <SelectItem value="org_viewer">Viewer</SelectItem>
                <SelectItem value="org_member">Member</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end">
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

      <Card>
        <CardHeader>
          <CardTitle>Invite user</CardTitle>
          <CardDescription>
            Create a local invite link. Team access can be assigned after the user joins.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="users-invite-email">Email</Label>
            <Input
              id="users-invite-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="teammate@example.com"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Org role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="org_admin">Admin</SelectItem>
                <SelectItem value="org_viewer">Viewer</SelectItem>
                <SelectItem value="org_member">Member</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
          <CardDescription>Org-level roles define product-wide access.</CardDescription>
        </CardHeader>
        <CardContent>
          {membersQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading members...</p>
          ) : members.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No members found"
              description="Invite or create the first user to start assigning team access."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => (
                  <TableRow
                    key={member.user_id}
                    className={member.status !== "active" ? "opacity-60" : undefined}
                  >
                    <TableCell>
                      <div className="font-medium">{member.email}</div>
                      {member.name ? (
                        <div className="text-xs text-muted-foreground">{member.name}</div>
                      ) : null}
                    </TableCell>
                    <TableCell className="capitalize">{member.status}</TableCell>
                    <TableCell>
                      <Select
                        value={member.role}
                        onValueChange={(value) =>
                          updateMemberMutation.mutate({
                            userId: member.user_id,
                            data: { role: value },
                          })
                        }
                        disabled={isPending || member.status !== "active"}
                      >
                        <SelectTrigger className="w-36">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="org_owner">Owner</SelectItem>
                          <SelectItem value="org_admin">Admin</SelectItem>
                          <SelectItem value="org_viewer">Viewer</SelectItem>
                          <SelectItem value="org_member">Member</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>{new Date(member.created_at).toLocaleDateString()}</TableCell>
                    <TableCell className="text-right">
                      {member.status === "active" ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          disabled={isPending}
                          onClick={() =>
                            updateMemberStatusMutation.mutate({
                              userId: member.user_id,
                              data: { status: "inactive" },
                            })
                          }
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
                          onClick={() =>
                            updateMemberStatusMutation.mutate({
                              userId: member.user_id,
                              data: { status: "active" },
                            })
                          }
                          aria-label="Reactivate user"
                        >
                          <RotateCcw />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pending invites</CardTitle>
          <CardDescription>Links are shown only at invite creation time.</CardDescription>
        </CardHeader>
        <CardContent>
          {invitesQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading invites...</p>
          ) : pendingInvites.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending invites.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pendingInvites.map((invite) => (
                  <TableRow key={invite.id}>
                    <TableCell>{invite.email}</TableCell>
                    <TableCell>{formatOrgRole(invite.role)}</TableCell>
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
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          disabled={isPending}
                          onClick={() => revokeInviteMutation.mutate({ inviteId: invite.id })}
                          aria-label="Revoke invite"
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function formatOrgRole(value: string) {
  if (value === "org_owner") return "Owner";
  if (value === "org_admin") return "Admin";
  if (value === "org_member") return "Member";
  return "Viewer";
}
