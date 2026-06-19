import { MoreHorizontal, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { GuardrailPolicyResponse } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { guardrailPolicyStatus, policyRuleSummary } from "../lib/guardrail-helpers";

export function GuardrailPoliciesTab({
  policies,
  isLoading,
  canManage,
  onCreate,
  onEdit,
  onDelete,
  deletePending,
}: {
  policies: GuardrailPolicyResponse[];
  isLoading: boolean;
  canManage: boolean;
  onCreate: () => void;
  onEdit: (policy: GuardrailPolicyResponse) => void;
  onDelete: (policy: GuardrailPolicyResponse) => void;
  deletePending: boolean;
}) {
  const columns: DataTableColumn<GuardrailPolicyResponse>[] = [
    {
      key: "policy",
      header: "Policy",
      cell: (policy) => (
        <>
          <div className="font-medium">{policy.name}</div>
          <div className="text-sm text-muted-foreground">
            {policy.description ?? "No description"}
          </div>
        </>
      ),
    },
    {
      key: "mode",
      header: "Mode",
      cell: (policy) => (
        <Badge variant={policy.enforcement_mode === "enforce" ? "default" : "outline"}>
          {policy.enforcement_mode}
        </Badge>
      ),
    },
    {
      key: "rules",
      header: "Rules",
      className: "max-w-xl",
      cell: (policy) => (
        <span className="line-clamp-2 text-sm text-muted-foreground">
          {policyRuleSummary(policy) || "No rules"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (policy) => {
        const status = guardrailPolicyStatus(policy);
        return <StatusBadge variant={status.variant}>{status.label}</StatusBadge>;
      },
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "Actions",
            align: "right" as const,
            headClassName: "w-24",
            cell: (policy: GuardrailPolicyResponse) => (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Actions for ${policy.name}`}
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onEdit(policy)}>
                    <Pencil />
                    Edit policy
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => onDelete(policy)}
                    disabled={deletePending}
                  >
                    <Trash2 />
                    Delete policy
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ),
          },
        ]
      : []),
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policies</CardTitle>
        <CardDescription>
          Define reusable guardrail policies. They only affect traffic after assignment.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={policies}
          loading={isLoading}
          getRowKey={(policy) => policy.id}
          empty={{
            icon: ShieldCheck,
            title: "No guardrails yet",
            description: "Create a policy to start inspecting prompts and responses.",
            action: canManage ? (
              <Button onClick={onCreate}>
                <Plus data-icon="inline-start" />
                New guardrail policy
              </Button>
            ) : undefined,
          }}
        />
      </CardContent>
    </Card>
  );
}
