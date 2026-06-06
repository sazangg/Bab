import { Link } from "react-router-dom";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { EffectiveAccessSummary } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

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
          {summary.access_policy ? (
            <p className="text-sm">
              Policy: <span className="font-medium">{summary.access_policy.name}</span> from{" "}
              {summary.access_policy.source_scope} scope
            </p>
          ) : null}
        </div>
        <div className="space-y-2 text-sm">
          <p>{summary.routes.length} routable provider/model route(s)</p>
          {summary.routes.slice(0, 3).map((route) => (
            <div key={`${route.credential_pool_id}-${route.model_offering_id}`}>
              <Link className="hover:underline" to={`/providers/${route.provider_id}`}>
                {route.alias ?? route.provider_model}
              </Link>
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
