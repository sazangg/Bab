import type { APIRequestContext } from "@playwright/test";

import { apiLogin, apiPost, type Headers } from "./api";

type Team = { id: string; name: string };
type Project = { id: string; name: string; team_id: string };
type Member = { user_id: string; email: string };
type Provider = { id: string; name: string; display_name?: string };
type Pool = { id: string };
type Credential = { id: string };
type ModelOffering = { id: string; provider_model_name: string };

export function uniqueName(prefix: string) {
  return `${prefix} ${Date.now()} ${Math.random().toString(16).slice(2, 8)}`;
}

export function uniqueEmail(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`;
}

export async function createTeam(request: APIRequestContext, headers: Headers, name: string) {
  return apiPost<Team>(request, "/api/v1/teams", headers, { name });
}

export async function createProject(
  request: APIRequestContext,
  headers: Headers,
  teamId: string,
  name: string,
) {
  return apiPost<Project>(request, `/api/v1/teams/${teamId}/projects`, headers, { name });
}

export async function createMember(
  request: APIRequestContext,
  headers: Headers,
  email: string,
  password: string,
) {
  return apiPost<Member>(request, "/api/v1/auth/members", headers, {
    email,
    password,
    role: "org_member",
  });
}

export async function addTeamAdmin(
  request: APIRequestContext,
  headers: Headers,
  teamId: string,
  userId: string,
) {
  await apiPost(request, `/api/v1/teams/${teamId}/members`, headers, {
    user_id: userId,
    role: "team_admin",
  });
}

export async function addProjectAdmin(
  request: APIRequestContext,
  headers: Headers,
  projectId: string,
  userId: string,
) {
  await apiPost(request, `/api/v1/projects/${projectId}/members`, headers, {
    user_id: userId,
    role: "project_admin",
  });
}

export async function createPermissionFixture(request: APIRequestContext) {
  const ownerHeaders = await apiLogin(request);
  const suffix = uniqueName("E2E");
  const teamA = await createTeam(request, ownerHeaders, `${suffix} Team A`);
  const teamB = await createTeam(request, ownerHeaders, `${suffix} Team B`);
  const projectA = await createProject(request, ownerHeaders, teamA.id, `${suffix} Project A1`);
  const projectB = await createProject(request, ownerHeaders, teamB.id, `${suffix} Project B1`);
  const teamAdminEmail = uniqueEmail("team-admin");
  const projectAdminEmail = uniqueEmail("project-admin");
  const teamAdmin = await createMember(
    request,
    ownerHeaders,
    teamAdminEmail,
    "team-admin-password",
  );
  const projectAdmin = await createMember(
    request,
    ownerHeaders,
    projectAdminEmail,
    "project-admin-password",
  );
  await addTeamAdmin(request, ownerHeaders, teamA.id, teamAdmin.user_id);
  await addProjectAdmin(request, ownerHeaders, projectA.id, projectAdmin.user_id);

  return {
    teamA,
    teamB,
    projectA,
    projectB,
    teamAdminEmail,
    projectAdminEmail,
  };
}

export async function createProviderRouteFixture(request: APIRequestContext) {
  const headers = await apiLogin(request);
  const name = uniqueName("e2e-provider").toLowerCase().replaceAll(" ", "-");
  const provider = await apiPost<Provider>(request, "/api/v1/providers", headers, {
    name,
    base_url: `https://${name}.example.test/v1`,
  });
  const pool = await apiPost<Pool>(request, `/api/v1/providers/${provider.id}/pools`, headers, {
    name: "Primary",
  });
  const credential = await apiPost<Credential>(
    request,
    `/api/v1/providers/${provider.id}/credentials`,
    headers,
    { name: "Credential", api_key: "test-key" },
  );
  await apiPost(
    request,
    `/api/v1/providers/${provider.id}/pools/${pool.id}/credentials`,
    headers,
    { provider_credential_id: credential.id },
  );
  const model = await apiPost<ModelOffering>(
    request,
    `/api/v1/providers/${provider.id}/offerings`,
    headers,
    { provider_model_name: `${name}-model` },
  );
  return { provider, pool, model };
}
