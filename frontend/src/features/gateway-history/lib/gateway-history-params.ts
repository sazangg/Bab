import type { ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams } from "@/shared/api/generated/schemas";

export const GATEWAY_HISTORY_PAGE_SIZE = 25;

type HistoryWindow = NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["window"]>;
type HistoryStatus = NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["status"]>;
type HistoryFallback =
  NonNullable<ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams["fallback"]>;

export function buildGatewayHistoryParams({
  window,
  status,
  fallback,
  search,
  page,
}: {
  window: HistoryWindow;
  status: HistoryStatus | "all";
  fallback: HistoryFallback | "all";
  search: string;
  page: number;
}): ListGatewayRequestsApiV1GatewayHistoryRequestsGetParams {
  return {
    window,
    status: status === "all" ? undefined : status,
    fallback: fallback === "all" ? undefined : fallback,
    search: search || undefined,
    limit: GATEWAY_HISTORY_PAGE_SIZE,
    offset: page * GATEWAY_HISTORY_PAGE_SIZE,
  };
}
