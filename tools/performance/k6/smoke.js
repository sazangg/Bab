import http from "k6/http";
import { sleep } from "k6";
import {
  adminHeaders,
  assertOk,
  baseUrl,
  context,
  gatewayHeaders,
  login,
} from "./common.js";

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: { checks: ["rate==1"] },
  summaryTrendStats: ["avg", "min", "med", "p(95)", "p(99)", "max"],
};

export function setup() {
  const ctx = context();
  return { ctx, token: login(ctx) };
}

export default function (data) {
  assertOk(http.get(`${baseUrl}/api/v1/health`), "health");
  assertOk(http.get(`${baseUrl}/api/v1/ready`), "readiness");
  assertOk(http.get(`${baseUrl}/metrics`), "metrics");
  assertOk(
    http.get(`${baseUrl}/api/v1/auth/me`, { headers: adminHeaders(data.token) }),
    "authenticated request",
  );
  assertOk(
    http.post(
      `${baseUrl}/v1/chat/completions`,
      JSON.stringify({
        model: "benchmark-chat",
        messages: [{ role: "user", content: "hello" }],
      }),
      { headers: gatewayHeaders(data.ctx) },
    ),
    "gateway request",
  );
  sleep(0.1);
}
