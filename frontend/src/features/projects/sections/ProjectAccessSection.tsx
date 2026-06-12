import { isAxiosError } from "axios";

import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";
import {
  useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet,
  useListProjectAccessibleModelsApiV1ProjectsProjectIdAccessibleModelsGet,
} from "@/shared/api/generated/projects/projects";
import { EffectiveAccessSummaryCard } from "@/features/projects/components/EffectiveAccessSummaryCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

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
          {modelsQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading accessible models...</p>
          ) : blocked ? (
            <p className="text-sm text-muted-foreground">
              Models are blocked until the project has an effective access policy.
            </p>
          ) : modelsQuery.isError ? (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-destructive">Accessible models could not be loaded.</p>
              <Button variant="outline" size="sm" onClick={() => modelsQuery.refetch()}>
                Retry
              </Button>
            </div>
          ) : models.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No models are currently routable for this project.
            </p>
          ) : (
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Pool</TableHead>
                    <TableHead>Source policy</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((model) => (
                    <TableRow key={`${model.provider_id}:${model.model_offering_id}`}>
                      <TableCell>
                        <div className="font-medium">{model.alias ?? model.id}</div>
                        {model.alias ? (
                          <div className="text-xs text-muted-foreground">{model.id}</div>
                        ) : null}
                      </TableCell>
                      <TableCell>{model.provider_name}</TableCell>
                      <TableCell>{model.pool_name}</TableCell>
                      <TableCell>
                        <div>{model.access_policy_name ?? "Inherited policy"}</div>
                        <div className="text-xs capitalize text-muted-foreground">
                          {model.source_scope ?? "organization"}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      <PolicyScopeSection target={{ type: "project", projectId, teamId }} canManage={canManage} />
    </div>
  );
}
