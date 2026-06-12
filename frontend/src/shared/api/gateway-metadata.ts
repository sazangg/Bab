import { useQuery } from "@tanstack/react-query";

import { apiMutator } from "@/shared/api/orval-mutator";

export type GatewayMetadata = {
  public_base_url: string | null;
  virtual_key_prefix: string;
  default_virtual_key_expiration_days: number | null;
};

type GatewayMetadataResponse = {
  data: GatewayMetadata;
  status: number;
  headers: Headers;
};

export function useGatewayMetadata() {
  return useQuery({
    queryKey: ["/api/v1/settings/gateway-metadata"],
    queryFn: () =>
      apiMutator<GatewayMetadataResponse>("/api/v1/settings/gateway-metadata", {
        method: "GET",
      }),
  });
}

export function resolveGatewayBaseUrl(publicBaseUrl?: string | null) {
  if (publicBaseUrl?.trim()) return publicBaseUrl.replace(/\/+$/, "");
  const envBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  if (envBaseUrl?.trim()) return envBaseUrl.replace(/\/+$/, "");
  return import.meta.env.DEV ? "http://localhost:8000" : null;
}
