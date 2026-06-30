import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Plus, Power, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type {
  CredentialPoolCredentialResponse,
  CredentialPoolResponse,
  ProviderCredentialResponse,
} from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import {
  formatHealth,
  poolMembershipSchema,
  type PoolMembershipInput,
  type PoolMembershipValues,
} from "../../lib/resources-helpers";

export function CredentialPoolMembersPanel({
  providerId,
  pool,
  credentials,
  members,
  isLoading,
  isError,
  isAdding,
  onAdd,
  onUpdate,
  onDelete,
  canManage,
}: {
  providerId: string;
  pool: CredentialPoolResponse | null;
  credentials: ProviderCredentialResponse[];
  members: CredentialPoolCredentialResponse[];
  isLoading: boolean;
  isError: boolean;
  isAdding: boolean;
  onAdd: (pool: CredentialPoolResponse, values: PoolMembershipValues) => void;
  onUpdate: (
    pool: CredentialPoolResponse,
    member: CredentialPoolCredentialResponse,
    values: Partial<Pick<CredentialPoolCredentialResponse, "priority" | "weight" | "is_active">>,
  ) => void;
  onDelete: (pool: CredentialPoolResponse, member: CredentialPoolCredentialResponse) => void;
  canManage: boolean;
}) {
  const [editMember, setEditMember] = useState<CredentialPoolCredentialResponse | null>(null);
  const [deleteMember, setDeleteMember] = useState<CredentialPoolCredentialResponse | null>(null);
  const form = useForm<PoolMembershipInput, unknown, PoolMembershipValues>({
    resolver: zodResolver(poolMembershipSchema),
    defaultValues: { provider_credential_id: "", priority: 100, weight: 1 },
  });
  const memberCredentialIds = new Set(members.map((member) => member.provider_credential_id));
  const activeCredentials = credentials.filter((credential) => credential.is_active);
  const availableCredentials = credentials.filter(
    (credential) => credential.is_active && !memberCredentialIds.has(credential.id),
  );
  const firstAvailableCredentialId = availableCredentials[0]?.id ?? "";
  const selectedCredentialId = useWatch({ control: form.control, name: "provider_credential_id" });

  useEffect(() => {
    form.reset({
      provider_credential_id: firstAvailableCredentialId,
      priority: 100,
      weight: 1,
    });
  }, [pool?.id, firstAvailableCredentialId, form]);

  if (!pool) {
    return (
      <div className="rounded-md border py-8 text-center text-sm text-muted-foreground">
        Create a pool before assigning credentials.
      </div>
    );
  }

  const sortedMembers = [...members].sort((a, b) => a.priority - b.priority);

  const columns: DataTableColumn<CredentialPoolCredentialResponse>[] = [
    {
      key: "credential",
      header: "Credential",
      cell: (member) => (
        <>
          <div className="font-medium">{member.credential.name}</div>
          <p className="font-mono text-xs text-muted-foreground">{member.credential.key_prefix}</p>
        </>
      ),
    },
    {
      key: "priority",
      header: "Priority",
      align: "right",
      className: "font-mono text-xs",
      cell: (member) => member.priority,
    },
    {
      key: "weight",
      header: "Weight",
      align: "right",
      className: "font-mono text-xs",
      cell: (member) => member.weight,
    },
    {
      key: "health",
      header: "Health",
      cell: (member) => {
        const health = formatHealth(member.credential.health_status);
        return <StatusBadge variant={health.variant}>{health.label}</StatusBadge>;
      },
    },
    {
      key: "status",
      header: "Status",
      cell: (member) => (
        <StatusBadge variant={member.is_active && member.credential.is_active ? "active" : "inactive"}>
          {member.is_active
            ? member.credential.is_active
              ? "Active"
              : "Credential disabled"
            : "Membership disabled"}
        </StatusBadge>
      ),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            headClassName: "w-[1%]",
            className: "flex justify-end gap-1",
            cell: (member: CredentialPoolCredentialResponse) => (
              <>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => setEditMember(member)}
                  title="Edit membership"
                  aria-label="Edit membership"
                >
                  <Pencil />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => onUpdate(pool, member, { is_active: !member.is_active })}
                  title={member.is_active ? "Disable membership" : "Reactivate membership"}
                  aria-label={member.is_active ? "Disable membership" : "Reactivate membership"}
                >
                  {member.is_active ? <Power /> : <RotateCcw />}
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => setDeleteMember(member)}
                  title="Remove from pool"
                  aria-label="Remove from pool"
                >
                  <Trash2 />
                </Button>
              </>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 rounded-md border p-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h4 className="font-medium">{pool.name} credentials</h4>
          <p className="text-sm text-muted-foreground">
            Priority orders deterministic routing. Weight only affects weighted routing.
          </p>
        </div>
        {canManage ? (
          <form
            className="grid gap-2 md:grid-cols-[minmax(220px,1fr)_92px_92px_auto]"
            onSubmit={form.handleSubmit((values) => {
              if (!pool) return;
              onAdd(pool, values);
            })}
          >
            <Select
              value={selectedCredentialId}
              onValueChange={(value) => form.setValue("provider_credential_id", value)}
              disabled={!providerId || availableCredentials.length === 0}
            >
              <SelectTrigger aria-label="Credential to assign">
                <SelectValue placeholder="Credential" />
              </SelectTrigger>
              <SelectContent>
                {availableCredentials.map((credential) => (
                  <SelectItem key={credential.id} value={credential.id}>
                    {credential.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Membership priority"
              title="Priority"
              placeholder="Priority"
              type="number"
              min={0}
              {...form.register("priority", { valueAsNumber: true })}
            />
            <Input
              aria-label="Membership weight"
              title="Weight"
              placeholder="Weight"
              type="number"
              min={1}
              {...form.register("weight", { valueAsNumber: true })}
            />
            <Button type="submit" disabled={isAdding || !providerId || availableCredentials.length === 0}>
              <Plus />
              Assign
            </Button>
          </form>
        ) : null}
      </div>

      <DataTable
        columns={columns}
        data={sortedMembers}
        loading={isLoading}
        error={isError ? "Pool credentials could not be loaded." : undefined}
        getRowKey={(member) => member.id}
        rowClassName={(member) =>
          !member.is_active || !member.credential.is_active ? "opacity-60" : undefined
        }
        empty={{
          title: "This pool is empty.",
          description:
            activeCredentials.length === 0
              ? "Routing through it will fail because this provider has no active credentials to assign."
              : availableCredentials.length === 0
                ? "All active credentials are already attached to this pool."
                : "Routing through it will fail until an active credential is assigned.",
        }}
      />

      <PoolMembershipSheet
        member={editMember}
        onClose={() => setEditMember(null)}
        onSubmit={(values) => {
          if (!editMember) return;
          onUpdate(pool, editMember, values);
          setEditMember(null);
        }}
      />
      <Dialog open={Boolean(deleteMember)} onOpenChange={(open) => !open && setDeleteMember(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove credential from pool?</DialogTitle>
            <DialogDescription>
              {deleteMember
                ? `${deleteMember.credential.name} will stop being selected by ${pool.name}. The credential itself remains available.`
                : "This credential will stop being selected by the pool."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={!deleteMember}
              onClick={() => {
                if (!deleteMember) return;
                onDelete(pool, deleteMember);
                setDeleteMember(null);
              }}
            >
              Remove
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

function PoolMembershipSheet({
  member,
  onClose,
  onSubmit,
}: {
  member: CredentialPoolCredentialResponse | null;
  onClose: () => void;
  onSubmit: (values: Pick<PoolMembershipValues, "priority" | "weight">) => void;
}) {
  const form = useForm<
    Pick<PoolMembershipInput, "priority" | "weight">,
    unknown,
    Pick<PoolMembershipValues, "priority" | "weight">
  >({
    resolver: zodResolver(poolMembershipSchema.pick({ priority: true, weight: true })),
    defaultValues: { priority: 100, weight: 1 },
  });

  useEffect(() => {
    if (!member) return;
    form.reset({ priority: member.priority, weight: member.weight });
  }, [member, form]);

  return (
    <Sheet open={Boolean(member)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit pool credential</SheetTitle>
          <SheetDescription>
            Update this credential's routing metadata for this pool only.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 overflow-y-auto px-6 py-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="pool-membership-priority">Priority</Label>
            <Input
              id="pool-membership-priority"
              type="number"
              min={0}
              {...form.register("priority", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Lower numbers are preferred by priority-based policies.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pool-membership-weight">Weight</Label>
            <Input
              id="pool-membership-weight"
              type="number"
              min={1}
              {...form.register("weight", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Higher numbers receive more traffic only when this pool uses weighted routing.
            </p>
          </div>
        </form>
        <SheetFooter>
          <Button disabled={!member} onClick={form.handleSubmit(onSubmit)}>
            Save changes
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
