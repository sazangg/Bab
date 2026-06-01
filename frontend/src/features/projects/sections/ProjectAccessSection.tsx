import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";

export function ProjectAccessSection({
  projectId,
  teamId,
  canManage,
}: {
  projectId: string;
  teamId: string;
  canManage: boolean;
}) {
  return (
    <PolicyScopeSection
      target={{ type: "project", projectId, teamId }}
      canManage={canManage}
    />
  );
}
