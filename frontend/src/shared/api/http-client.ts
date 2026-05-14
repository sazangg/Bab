import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { getAccessToken, setAccessToken } from "@/shared/auth/access-token-store";

type RetriableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
};

export const httpClient = axios.create({
  withCredentials: true,
});

const refreshClient = axios.create({
  withCredentials: true,
});

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

    try {
      const refreshResponse = await refreshClient.post("/api/v1/auth/refresh");
      const accessToken = refreshResponse.data?.access_token;
      if (typeof accessToken !== "string") {
        throw error;
      }

      setAccessToken(accessToken);
      originalRequest.headers.set("Authorization", `Bearer ${accessToken}`);
      return httpClient(originalRequest);
    } catch (refreshError) {
      setAccessToken(null);
      throw refreshError;
    }
  },
);
