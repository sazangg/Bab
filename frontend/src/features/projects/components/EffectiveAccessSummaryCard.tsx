import { Link } from "react-router-dom";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { EffectiveAccessSummary } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

type EffectiveAccessPolicy = NonNullable<EffectiveAccessSummary["access_policy"]>;

export function EffectiveAccessSummaryCard({
  summary,
  isLoading,
}: {
  summary?: EffectiveAccessSummary;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Checking effective access...</p>;
  }
  if (!summary) return null;
  const accessPolicies =
    (summary as EffectiveAccessSummary & { access_policies?: EffectiveAccessPolicy[] })
      .access_policies ??
    (summary.access_policy ? [summary.access_policy] : []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Effective access</CardTitle>
        <CardDescription>
          {summary.is_usable
            ? "This resource currently has a usable gateway route."
            : summary.blocking_reason}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <StatusBadge variant={summary.is_usable ? "active" : "expired"}>
            {summary.is_usable ? "Usable" : summary.blocking_code?.replaceAll("_", " ")}
          </StatusBadge>
          <p className="text-sm text-muted-foreground">
            Ownership: organization {state(summary.ownership.organization_active)}, team{" "}
            {state(summary.ownership.team_active)}, project{" "}
            {state(summary.ownership.project_active)}
            {summary.ownership.key_active == null
              ? ""
              : `, key ${state(summary.ownership.key_active)}`}
          </p>
          {accessPolicies.length ? (
            <p className="text-sm">
              Policies:{" "}
              <span className="font-medium">
                {accessPolicies.map((policy) => policy.name).join(", ")}
              </span>
            </p>
          ) : null}
        </div>
        <div className="space-y-2 text-sm">
          <p>{summary.routes.length} routable provider/model candidate(s)</p>
          {summary.routes.slice(0, 3).map((route) => (
            <div key={`${route.credential_pool_id}-${route.model_offering_id}`}>
              <Link className="hover:underline" to={`/providers/${route.provider_id}`}>
                {route.provider_model}
              </Link>
              {"access_policy_name" in route && route.access_policy_name ? (
                <span className="text-muted-foreground"> · {route.access_policy_name}</span>
              ) : null}
            </div>
          ))}
          <p className="text-muted-foreground">
            {summary.limit_policies.length} effective limit policy reference(s)
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function state(value: boolean) {
  return value ? "active" : "inactive";
}
