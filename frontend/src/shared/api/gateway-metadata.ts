import { useGetGatewayMetadataApiV1SettingsGatewayMetadataGet } from "@/shared/api/generated/settings/settings";
import type { GatewayMetadataResponse } from "@/shared/api/generated/schemas";

export type GatewayMetadata = GatewayMetadataResponse;

export const useGatewayMetadata = useGetGatewayMetadataApiV1SettingsGatewayMetadataGet;

export function resolveGatewayBaseUrl(publicBaseUrl?: string | null) {
  if (publicBaseUrl?.trim()) return publicBaseUrl.replace(/\/+$/, "");
  const envBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  if (envBaseUrl?.trim()) return envBaseUrl.replace(/\/+$/, "");
  return import.meta.env.DEV ? "http://localhost:8000" : null;
}
