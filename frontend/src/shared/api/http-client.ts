import axios from "axios";

import { getAccessToken } from "@/shared/auth/access-token-store";

export const httpClient = axios.create({
  withCredentials: true,
});

httpClient.interceptors.request.use((config) => {
  const accessToken = getAccessToken();

  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }

  return config;
});
