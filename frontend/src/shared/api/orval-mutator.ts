import { httpClient } from "@/shared/api/http-client";

export async function apiMutator<TData>(url: string, options: RequestInit = {}): Promise<TData> {
  const headers = Object.fromEntries(new Headers(options.headers).entries());
  const response = await httpClient.request<TData>({
    url,
    method: options.method,
    headers,
    data: typeof options.body === "string" ? JSON.parse(options.body) : options.body,
    signal: options.signal ?? undefined,
  });

  return {
    data: response.data,
    status: response.status,
    headers: new Headers(response.headers as Record<string, string>),
  } as TData;
}
