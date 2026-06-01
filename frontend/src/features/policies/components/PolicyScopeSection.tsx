import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useListAccessPoliciesApiV1PoliciesAccessGet,
  useListLimitPoliciesApiV1PoliciesLimitsGet,
  useListPolicyAssignmentsApiV1PoliciesAssignmentsGet,
} from "@/shared/api/generated/policies/policies";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge } from "@/shared/components/StatusBadge";

type ScopeTarget =
  | { type: "team"; teamId: string }
  | { type: "project"; projectId: string; teamId: string };

export function PolicyScopeSection({
  target,
  canManage,
}: {
  target: ScopeTarget;
  canManage: boolean;
}) {
  const accessQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const limitsQuery = useListLimitPoliciesApiV1PoliciesLimitsGet();
  const assignmentsQuery = useListPolicyAssignmentsApiV1PoliciesAssignmentsGet();
  const accessPolicies = accessQuery.data?.status === 200 ? accessQuery.data.data : [];
  const limitPolicies = limitsQuery.data?.status === 200 ? limitsQuery.data.data : [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const scopedAssignments = assignments.filter((assignment) => {
    if (target.type === "team") {
      return assignment.scope_type === "team" && assignment.team_id === target.teamId;
    }
    return assignment.scope_type === "project" && assignment.project_id === target.projectId;
  });
  const accessById = new Map(accessPolicies.map((policy) => [policy.id, policy]));
  const limitById = new Map(limitPolicies.map((policy) => [policy.id, policy]));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policies</CardTitle>
        <CardDescription>
          Assigned access policies define available provider routes. Assigned limit policies define
          budgets and caps. Higher scopes still apply.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {scopedAssignments.length === 0 ? (
          <EmptyState
            title="No policies assigned"
            description="Assign reusable access and limit policies from the Policies page."
            action={
              canManage ? (
                <Button asChild size="sm">
                  <Link to="/policies">Open policies</Link>
                </Button>
              ) : null
            }
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {scopedAssignments.map((assignment) => {
              const policy =
                assignment.policy_type === "access"
                  ? accessById.get(assignment.access_policy_id ?? "")
                  : limitById.get(assignment.limit_policy_id ?? "");
              return (
                <div key={assignment.id} className="rounded-md border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{policy?.name ?? "Unknown policy"}</p>
                      <p className="text-xs capitalize text-muted-foreground">
                        {assignment.policy_type} policy
                      </p>
                    </div>
                    <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
                      {assignment.is_active ? "Active" : "Inactive"}
                    </StatusBadge>
                  </div>
                  {policy?.description ? (
                    <p className="mt-2 text-xs text-muted-foreground">{policy.description}</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
