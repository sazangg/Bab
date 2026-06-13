import { Pencil, Power, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { cn } from "@/lib/utils";
import type { CredentialPoolResponse } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { formatDateTime } from "../../lib/format";
import { formatRoutingPolicy } from "../../lib/resources-helpers";
import type { CredentialPoolValues } from "../../lib/schemas";
import { CredentialPoolSheet } from "./CredentialPoolSheet";

export function CredentialPoolsTable({
  pools,
  selectedPoolId,
  isLoading,
  isError,
  onSelect,
  onUpdate,
  onDeactivate,
  onReactivate,
  canManage,
}: {
  pools: CredentialPoolResponse[];
  selectedPoolId: string | null;
  isLoading: boolean;
  isError: boolean;
  onSelect: (poolId: string) => void;
  onUpdate: (pool: CredentialPoolResponse, values: CredentialPoolValues) => void;
  onDeactivate: (pool: CredentialPoolResponse) => void;
  onReactivate: (pool: CredentialPoolResponse) => void;
  canManage: boolean;
}) {
  const [editPool, setEditPool] = useState<CredentialPoolResponse | null>(null);

  const columns: DataTableColumn<CredentialPoolResponse>[] = [
    {
      key: "pool",
      header: "Pool",
      cell: (pool) => (
        <>
          <div className="font-medium">{pool.name}</div>
          <p className="text-xs text-muted-foreground">{pool.description || "No description"}</p>
        </>
      ),
    },
    {
      key: "policy",
      header: "Policy",
      cell: (pool) => formatRoutingPolicy(pool.selection_policy),
    },
    {
      key: "active_keys",
      header: "Active keys",
      align: "right",
      className: "tabular-nums",
      cell: (pool) => `${pool.active_credential_count}/${pool.credential_count}`,
    },
    {
      key: "status",
      header: "Status",
      cell: (pool) => (
        <StatusBadge variant={pool.is_active ? "active" : "inactive"}>
          {pool.is_active ? "Active" : "Disabled"}
        </StatusBadge>
      ),
    },
    {
      key: "updated",
      header: "Updated",
      className: "text-xs text-muted-foreground",
      cell: (pool) => formatDateTime(pool.updated_at),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            headClassName: "w-[1%]",
            className: "flex justify-end gap-1",
            cell: (pool: CredentialPoolResponse) => (
              <>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    setEditPool(pool);
                  }}
                  title="Edit pool"
                  aria-label="Edit pool"
                >
                  <Pencil />
                </Button>
                {pool.is_active ? (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDeactivate(pool);
                    }}
                    title="Disable pool"
                    aria-label="Disable pool"
                  >
                    <Power />
                  </Button>
                ) : (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      onReactivate(pool);
                    }}
                    title="Reactivate pool"
                    aria-label="Reactivate pool"
                  >
                    <RotateCcw />
                  </Button>
                )}
              </>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <DataTable
        columns={columns}
        data={pools}
        loading={isLoading}
        error={isError ? "Pools could not be loaded." : undefined}
        getRowKey={(pool) => pool.id}
        onRowClick={(pool) => onSelect(pool.id)}
        rowClassName={(pool) =>
          cn(!pool.is_active && "opacity-60", pool.id === selectedPoolId && "bg-muted/40")
        }
        empty={{ title: "No pools added yet." }}
      />
      <CredentialPoolSheet
        open={Boolean(editPool)}
        onOpenChange={(open) => !open && setEditPool(null)}
        title="Edit credential pool"
        description="Update how this pool selects active credentials."
        submitLabel="Save changes"
        initialValue={editPool}
        onSubmit={(values) => {
          if (!editPool) return;
          onUpdate(editPool, values);
          setEditPool(null);
        }}
      />
    </>
  );
}
