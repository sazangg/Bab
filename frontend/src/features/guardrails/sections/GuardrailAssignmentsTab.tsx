import { MoreHorizontal, Pencil, ShieldCheck, Trash2 } from "lucide-react";

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
import type { GuardrailAssignmentResponse } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { guardrailAssignmentStatus, labelAssignmentScope } from "../lib/guardrail-helpers";

export function GuardrailAssignmentsTab({
  assignments,
  isLoading,
  canAssign,
  scopeLabels,
  onEdit,
  onToggleActive,
  onRemove,
  togglePending,
  removePending,
}: {
  assignments: GuardrailAssignmentResponse[];
  isLoading: boolean;
  canAssign: boolean;
  scopeLabels: Record<string, string>;
  onEdit: (assignment: GuardrailAssignmentResponse) => void;
  onToggleActive: (assignment: GuardrailAssignmentResponse) => void;
  onRemove: (assignment: GuardrailAssignmentResponse) => void;
  togglePending: boolean;
  removePending: boolean;
}) {
  const columns: DataTableColumn<GuardrailAssignmentResponse>[] = [
    {
      key: "policy",
      header: "Policy",
      className: "font-medium",
      cell: (assignment) => assignment.policy_name,
    },
    {
      key: "scope",
      header: "Scope",
      cell: (assignment) => (
        <>
          <div>{assignment.scope_type}</div>
          <div className="text-xs text-muted-foreground">
            {labelAssignmentScope(assignment, scopeLabels)}
          </div>
        </>
      ),
    },
    {
      key: "mode",
      header: "Mode",
      cell: (assignment) => (
        <Badge variant={assignment.enforcement_mode === "dry_run" ? "outline" : "secondary"}>
          {assignment.enforcement_mode === "dry_run" ? "Dry run" : "Enforce"}
        </Badge>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (assignment) => {
        const status = guardrailAssignmentStatus(assignment);
        return <StatusBadge variant={status.variant}>{status.label}</StatusBadge>;
      },
    },
    ...(canAssign
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right" as const,
            headClassName: "w-12",
            cell: (assignment: GuardrailAssignmentResponse) => (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Actions for ${assignment.policy_name}`}
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onEdit(assignment)}>
                    <Pencil />
                    Edit assignment
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => onToggleActive(assignment)}
                    disabled={togglePending}
                  >
                    {assignment.is_active ? "Deactivate assignment" : "Activate assignment"}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => onRemove(assignment)}
                    disabled={removePending}
                  >
                    <Trash2 />
                    Remove assignment
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
        <CardTitle>Assignments</CardTitle>
        <CardDescription>
          Apply existing guardrail policies to an organization, team, project, or virtual key.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={assignments}
          loading={isLoading}
          getRowKey={(assignment) => assignment.id}
          empty={{
            icon: ShieldCheck,
            title: "No assignments",
            description: "Assign a policy to org, team, project, or virtual key.",
          }}
        />
      </CardContent>
    </Card>
  );
}
