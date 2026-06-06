import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";
import { useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet } from "@/shared/api/generated/projects/projects";
import { EffectiveAccessSummaryCard } from "@/features/projects/components/EffectiveAccessSummaryCard";

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
  const summary = accessQuery.data?.status === 200 ? accessQuery.data.data : undefined;
  return (
    <div className="flex flex-col gap-6">
      <EffectiveAccessSummaryCard summary={summary} isLoading={accessQuery.isPending} />
      <PolicyScopeSection target={{ type: "project", projectId, teamId }} canManage={canManage} />
    </div>
  );
}
