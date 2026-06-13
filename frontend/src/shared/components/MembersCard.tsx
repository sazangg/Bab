import { Trash2, UserPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type MembersCardMember = {
  user_id: string;
  email: string;
  name?: string | null;
  org_role: string;
  created_at: string;
};

export type MemberRoleOption = { value: string; label: string };

function formatOrgRole(value: string) {
  if (value === "org_owner") return "Org owner";
  if (value === "org_admin") return "Org admin";
  if (value === "org_viewer") return "Org viewer";
  if (value === "org_member") return "Org member";
  return value;
}

/**
 * Members management card shared by Team and Project detail pages: an add-member form
 * (assignable org member + scoped role) plus a DataTable of current members with inline
 * role editing and removal. Owns the add-form state; the scope-specific role choices,
 * wording, and remove guard come in as props.
 */
export function MembersCard<T extends MembersCardMember>({
  title,
  description,
  orgMembers,
  members,
  roleOptions,
  defaultRole,
  roleLabel = "Role",
  getRole,
  canManage,
  isLoading,
  isPending,
  onAdd,
  onRoleChange,
  onRemove,
  removeAriaLabel,
  emptyTitle,
  emptyDescription,
}: {
  title: string;
  description: React.ReactNode;
  orgMembers: { user_id: string; email: string }[];
  members: T[];
  roleOptions: MemberRoleOption[];
  defaultRole: string;
  roleLabel?: string;
  getRole: (member: T) => string;
  canManage: boolean;
  isLoading: boolean;
  isPending: boolean;
  onAdd: (userId: string, role: string) => void;
  onRoleChange: (member: T, role: string) => void;
  onRemove: (member: T) => void;
  removeAriaLabel?: (member: T) => string;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const [selectedUserId, setSelectedUserId] = useState("");
  const [role, setRole] = useState(defaultRole);
  const assignedIds = new Set(members.map((member) => member.user_id));
  const assignableMembers = orgMembers.filter((member) => !assignedIds.has(member.user_id));

  const roleLabelFor = (value: string) =>
    roleOptions.find((option) => option.value === value)?.label ?? value;

  const columns: DataTableColumn<T>[] = [
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
      key: "org_role",
      header: "Org role",
      cell: (member) => formatOrgRole(member.org_role),
    },
    {
      key: "role",
      header: roleLabel,
      cell: (member) =>
        canManage ? (
          <Select
            value={getRole(member)}
            onValueChange={(value) => onRoleChange(member, value)}
            disabled={isPending}
          >
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {roleOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          roleLabelFor(getRole(member))
        ),
    },
    {
      key: "added",
      header: "Added",
      cell: (member) => new Date(member.created_at).toLocaleDateString(),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "Actions",
            align: "right" as const,
            cell: (member: T) => (
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                disabled={isPending}
                onClick={() => onRemove(member)}
                aria-label={removeAriaLabel?.(member) ?? "Remove member"}
              >
                <Trash2 />
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {canManage ? (
          <div className="grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
            <div className="flex flex-col gap-1.5">
              <Label>User</Label>
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
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
            <div className="flex flex-col gap-1.5">
              <Label>{roleLabel}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                type="button"
                disabled={isPending || !selectedUserId || selectedUserId === "none"}
                onClick={() => {
                  onAdd(selectedUserId, role);
                  setSelectedUserId("");
                  setRole(defaultRole);
                }}
              >
                <UserPlus data-icon="inline-start" />
                Add member
              </Button>
            </div>
          </div>
        ) : null}

        <DataTable
          columns={columns}
          data={members}
          loading={isLoading}
          getRowKey={(member) => member.user_id}
          empty={{ title: emptyTitle, description: emptyDescription }}
        />
      </CardContent>
    </Card>
  );
}
