import { useMatch } from "react-router-dom";

import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";

export type Breadcrumb = {
  label: string;
  to?: string;
};

export function useBreadcrumbs(): Breadcrumb[] {
  const overviewMatch = useMatch("/");
  const projectsMatch = useMatch("/projects");
  const projectDetailMatch = useMatch("/projects/:projectId");
  const keyDetailMatch = useMatch("/projects/:projectId/keys/:keyId");
  const providersMatch = useMatch("/providers");
  const logsMatch = useMatch("/logs");
  const auditMatch = useMatch("/audit");
  const settingsMatch = useMatch("/settings");

  const projectId =
    projectDetailMatch?.params.projectId ?? keyDetailMatch?.params.projectId ?? null;
  const projectsQuery = useListProjectsApiV1ProjectsGet({
    query: { enabled: Boolean(projectId) },
  });
  const projectName =
    projectId && projectsQuery.data?.status === 200
      ? (projectsQuery.data.data.find((project) => project.id === projectId)?.name ?? "Project")
      : "Project";

  if (overviewMatch) {
    return [{ label: "Overview" }];
  }
  if (keyDetailMatch) {
    return [
      { label: "Projects", to: "/projects" },
      { label: projectName, to: `/projects/${keyDetailMatch.params.projectId}` },
      { label: "Key" },
    ];
  }
  if (projectDetailMatch) {
    return [{ label: "Projects", to: "/projects" }, { label: projectName }];
  }
  if (projectsMatch) {
    return [{ label: "Projects" }];
  }
  if (providersMatch) {
    return [{ label: "Providers" }];
  }
  if (logsMatch) {
    return [{ label: "Request logs" }];
  }
  if (auditMatch) {
    return [{ label: "Audit" }];
  }
  if (settingsMatch) {
    return [{ label: "Settings" }];
  }
  return [{ label: "Bab" }];
}
