import { isAxiosError } from "axios";

import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";
import {
  useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet,
  useListProjectAccessibleModelsApiV1ProjectsProjectIdAccessibleModelsGet,
} from "@/shared/api/generated/projects/projects";
import { EffectiveAccessSummaryCard } from "@/features/projects/components/EffectiveAccessSummaryCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";

export function ProjectAccessSection({
  projectId,
  teamId,
  canManage,
}: {
  projectId: string;
  teamId: string;
  canManage: boolean;
}) {
  const accessQuery =
    useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet(projectId);
  const modelsQuery =
    useListProjectAccessibleModelsApiV1ProjectsProjectIdAccessibleModelsGet(projectId);
  const summary = accessQuery.data?.status === 200 ? accessQuery.data.data : undefined;
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data : [];
  const blocked =
    isAxiosError(modelsQuery.error) && modelsQuery.error.response?.status === 409;
  return (
    <div className="flex flex-col gap-6">
      <EffectiveAccessSummaryCard summary={summary} isLoading={accessQuery.isPending} />
      <Card>
        <CardHeader>
          <CardTitle>Accessible models</CardTitle>
          <CardDescription>
            Models currently routable through this project's effective access policies.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {blocked ? (
            <p className="text-sm text-muted-foreground">
              Models are blocked until the project has an effective access policy.
            </p>
          ) : (
            <DataTable
              columns={[
                {
                  key: "model",
                  header: "Model",
                  cell: (model) => (
                    <>
                      <div className="font-medium">{model.alias ?? model.id}</div>
                      {model.alias ? (
                        <div className="text-xs text-muted-foreground">{model.id}</div>
                      ) : null}
                    </>
                  ),
                },
                { key: "provider", header: "Provider", cell: (model) => model.provider_name },
                { key: "pool", header: "Pool", cell: (model) => model.pool_name },
                {
                  key: "source",
                  header: "Source policy",
                  cell: (model) => (
                    <>
                      <div>{model.access_policy_name ?? "Inherited policy"}</div>
                      <div className="text-xs capitalize text-muted-foreground">
                        {model.source_scope ?? "organization"}
                      </div>
                    </>
                  ),
                },
              ]}
              data={models}
              loading={modelsQuery.isPending}
              error={modelsQuery.isError ? "Accessible models could not be loaded." : undefined}
              onRetry={() => void modelsQuery.refetch()}
              getRowKey={(model) => `${model.provider_id}:${model.model_offering_id}`}
              empty={{ title: "No models are currently routable for this project." }}
            />
          )}
        </CardContent>
      </Card>
      <PolicyScopeSection target={{ type: "project", projectId, teamId }} canManage={canManage} />
    </div>
  );
}
