import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { useAuthStore } from "@/features/auth/model/auth-store";
import { getAccessToken } from "@/shared/auth/access-token-store";

type RetriableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
};

export const httpClient = axios.create({
  withCredentials: true,
});

export const refreshClient = axios.create({
  withCredentials: true,
});

let refreshPromise: Promise<string> | null = null;

export function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = refreshClient
    .post("/api/v1/auth/refresh")
    .then((response) => {
      const accessToken = response.data?.access_token;
      if (typeof accessToken !== "string") {
        throw new Error("refresh response did not include an access token");
      }
      useAuthStore.getState().setSession(accessToken);
      return accessToken;
    })
    .catch((error) => {
      useAuthStore.getState().clearSession();
      throw error;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

httpClient.interceptors.request.use((config) => {
  const accessToken = getAccessToken();

  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }

  return config;
});

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetriableRequestConfig | undefined;
    const requestUrl = originalRequest?.url ?? "";

    if (
      error.response?.status !== 401 ||
      !originalRequest ||
      originalRequest._retry ||
      requestUrl.includes("/api/v1/auth/login") ||
      requestUrl.includes("/api/v1/auth/refresh")
    ) {
      throw error;
    }

    originalRequest._retry = true;
    const accessToken = await refreshAccessToken();
    originalRequest.headers.set("Authorization", `Bearer ${accessToken}`);
    return httpClient(originalRequest);
  },
);
