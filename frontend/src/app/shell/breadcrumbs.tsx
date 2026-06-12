import { useMatch } from "react-router-dom";

import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  useGetAccessPolicyApiV1PoliciesAccessPolicyIdGet,
  useGetLimitPolicyApiV1PoliciesLimitsPolicyIdGet,
} from "@/shared/api/generated/policies/policies";
import { canViewTeam } from "@/features/auth/lib/permissions";

export type Breadcrumb = {
  label: string;
  to?: string;
};

export function useBreadcrumbs(): Breadcrumb[] {
  const homeMatch = useMatch("/");
  const teamsMatch = useMatch("/teams");
  const teamDetailMatch = useMatch("/teams/:teamId");
  const projectsMatch = useMatch("/projects");
  const projectDetailMatch = useMatch("/projects/:projectId");
  const keyDetailMatch = useMatch("/projects/:projectId/keys/:keyId");
  const providersMatch = useMatch("/providers");
  const providerDetailMatch = useMatch("/providers/:providerId");
  const usageMatch = useMatch("/usage");
  const activityMatch = useMatch("/activity");
  const auditMatch = useMatch("/audit");
  const usersMatch = useMatch("/users");
  const settingsMatch = useMatch("/settings");
  const apiDocsMatch = useMatch("/api-docs");
  const policiesMatch = useMatch("/policies");
  const accessPolicyDetailMatch = useMatch("/policies/access/:policyId");
  const limitPolicyDetailMatch = useMatch("/policies/limits/:policyId");
  const virtualKeysMatch = useMatch("/virtual-keys");
  const guardrailsMatch = useMatch("/guardrails");
  const designSystemMatch = useMatch("/design-system");

  const projectId =
    projectDetailMatch?.params.projectId ?? keyDetailMatch?.params.projectId ?? null;
  const projectsQuery = useListProjectsApiV1ProjectsGet({
    query: { enabled: Boolean(projectId) },
  });
  const activeProject =
    projectId && projectsQuery.data?.status === 200
      ? projectsQuery.data.data.find((project) => project.id === projectId)
      : undefined;
  const projectName = activeProject?.name ?? "Project";
  const providerId = providerDetailMatch?.params.providerId ?? null;
  const providersQuery = useListProvidersApiV1ProvidersGet({
    query: { enabled: Boolean(providerId) },
  });
  const providerName =
    providerId && providersQuery.data?.status === 200
      ? (providersQuery.data.data.find((provider) => provider.id === providerId)?.name ??
        "Provider")
      : "Provider";
  const teamId = teamDetailMatch?.params.teamId ?? activeProject?.team_id ?? null;
  const teamsQuery = useListTeamsApiV1TeamsGet({
    query: { enabled: Boolean(teamId) },
  });
  const teamName =
    teamId && teamsQuery.data?.status === 200
      ? (teamsQuery.data.data.find((team) => team.id === teamId)?.name ??
        activeProject?.team_name ??
        "Team")
      : (activeProject?.team_name ?? "Team");
  const projectTeamId = activeProject?.team_id ?? null;
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const accessPolicyId = accessPolicyDetailMatch?.params.policyId ?? "";
  const accessPolicyQuery = useGetAccessPolicyApiV1PoliciesAccessPolicyIdGet(accessPolicyId, {
    query: { enabled: Boolean(accessPolicyId) },
  });
  const limitPolicyId = limitPolicyDetailMatch?.params.policyId ?? "";
  const limitPolicyQuery = useGetLimitPolicyApiV1PoliciesLimitsPolicyIdGet(limitPolicyId, {
    query: { enabled: Boolean(limitPolicyId) },
  });
  const canOpenProjectTeam = Boolean(projectTeamId && canViewTeam(currentUser, projectTeamId));

  if (homeMatch) {
    return [{ label: "Home" }];
  }
  if (teamDetailMatch) {
    return [{ label: "Teams", to: "/teams" }, { label: teamName }];
  }
  if (teamsMatch) {
    return [{ label: "Teams" }];
  }
  if (keyDetailMatch) {
    return [
      ...(projectTeamId
        ? [
            { label: "Teams", to: "/teams" },
            {
              label: teamName,
              to: canOpenProjectTeam ? `/teams/${projectTeamId}` : undefined,
            },
          ]
        : [{ label: "Projects", to: "/projects" }]),
      { label: projectName, to: `/projects/${keyDetailMatch.params.projectId}` },
      { label: "Key" },
    ];
  }
  if (projectDetailMatch) {
    return [
      ...(projectTeamId
        ? [
            { label: "Teams", to: "/teams" },
            {
              label: teamName,
              to: canOpenProjectTeam ? `/teams/${projectTeamId}` : undefined,
            },
          ]
        : [{ label: "Projects", to: "/projects" }]),
      { label: projectName },
    ];
  }
  if (projectsMatch) {
    return [{ label: "Projects" }];
  }
  if (providersMatch) {
    return [{ label: "Providers" }];
  }
  if (providerDetailMatch) {
    return [{ label: "Providers", to: "/providers" }, { label: providerName }];
  }
  if (usageMatch) {
    return [{ label: "Usage" }];
  }
  if (activityMatch) {
    return [{ label: "Activity" }];
  }
  if (auditMatch) {
    return [{ label: "Audit" }];
  }
  if (usersMatch) {
    return [{ label: "Users" }];
  }
  if (settingsMatch) {
    return [{ label: "Settings" }];
  }
  if (apiDocsMatch) {
    return [{ label: "API Docs" }];
  }
  if (accessPolicyDetailMatch) {
    return [
      { label: "Policies", to: "/policies" },
      {
        label:
          accessPolicyQuery.data?.status === 200
            ? accessPolicyQuery.data.data.name
            : "Access policy",
      },
    ];
  }
  if (limitPolicyDetailMatch) {
    return [
      { label: "Policies", to: "/policies" },
      {
        label:
          limitPolicyQuery.data?.status === 200 ? limitPolicyQuery.data.data.name : "Limit policy",
      },
    ];
  }
  if (policiesMatch) {
    return [{ label: "Policies" }];
  }
  if (virtualKeysMatch) {
    return [{ label: "Virtual keys" }];
  }
  if (guardrailsMatch) {
    return [{ label: "Guardrails" }];
  }
  if (designSystemMatch) {
    return [{ label: "Design system" }];
  }
  return [{ label: "Bab" }];
}
