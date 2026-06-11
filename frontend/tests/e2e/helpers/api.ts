import { expect, type APIRequestContext } from "@playwright/test";

export const backendURL = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:8011";

export type Headers = Record<string, string>;

export async function apiLogin(
  request: APIRequestContext,
  email = "owner@example.com",
  password = "correct-password",
): Promise<Headers> {
  const response = await request.post(`${backendURL}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return { Authorization: `Bearer ${body.access_token}` };
}

export async function apiGet<T>(
  request: APIRequestContext,
  path: string,
  headers: Headers,
): Promise<T> {
  const response = await request.get(`${backendURL}${path}`, { headers });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<T>;
}

export async function apiPost<T>(
  request: APIRequestContext,
  path: string,
  headers: Headers,
  data: unknown,
  expectedStatus = 201,
): Promise<T> {
  const response = await request.post(`${backendURL}${path}`, { headers, data });
  expect(response.status()).toBe(expectedStatus);
  return response.json() as Promise<T>;
}
