import { AllocationManagementSection } from "./AllocationManagementSection";

export function ProjectAccessSection({ projectId, teamId }: { projectId: string; teamId: string }) {
  return <AllocationManagementSection target={{ type: "project", projectId, teamId }} />;
}
