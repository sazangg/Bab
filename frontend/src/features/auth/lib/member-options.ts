import { useQuery } from "@tanstack/react-query";

import { httpClient } from "@/shared/api/http-client";

export type MemberOption = {
  user_id: string;
  email: string;
  name: string | null;
};

export function useTeamMemberOptions(teamId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["team-member-options", teamId],
    queryFn: async () => {
      const response = await httpClient.get<MemberOption[]>(
        `/api/v1/teams/${teamId}/member-options`,
      );
      return response.data;
    },
    enabled: Boolean(teamId) && enabled,
  });
}

export function useProjectMemberOptions(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["project-member-options", projectId],
    queryFn: async () => {
      const response = await httpClient.get<MemberOption[]>(
        `/api/v1/projects/${projectId}/member-options`,
      );
      return response.data;
    },
    enabled: Boolean(projectId) && enabled,
  });
}
