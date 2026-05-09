import type { AxiosRequestConfig } from "axios";

import { httpClient } from "@/shared/api/http-client";

export async function apiMutator<TData>(config: AxiosRequestConfig): Promise<TData> {
  const response = await httpClient.request<TData>(config);
  return response.data;
}
