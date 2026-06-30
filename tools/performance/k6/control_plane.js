import http from "k6/http";
import { adminHeaders, assertOk, baseUrl, context, login, scenarioOptions } from "./common.js";

export const options = scenarioOptions();

export function setup() {
  const ctx = context();
  return { ctx, token: login(ctx) };
}

export default function (data) {
  const params = { headers: adminHeaders(data.token) };
  const paths = [
    "/api/v1/usage/summary?window=30d",
    "/api/v1/usage/timeseries?window=30d&grain=day",
    "/api/v1/usage/filter-options?window=30d",
    "/api/v1/gateway-history/requests?window=30d&limit=50&offset=100",
    "/api/v1/virtual-keys?limit=50&offset=100",
    "/api/v1/policies/access-options?scope_type=org",
  ];
  for (const path of paths) {
    assertOk(http.get(`${baseUrl}${path}`, params), path);
  }
}
