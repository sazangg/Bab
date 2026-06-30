import http from "k6/http";
import {
  adminHeaders,
  assertOk,
  baseUrl,
  context,
  gatewayHeaders,
  login,
  scenarioOptions,
} from "./common.js";

export const options = scenarioOptions();

export function setup() {
  const ctx = context();
  return { ctx, token: login(ctx) };
}

export default function (data) {
  const gateway = { headers: gatewayHeaders(data.ctx) };
  for (let index = 0; index < 4; index += 1) {
    assertOk(
      http.post(
        `${baseUrl}/v1/chat/completions`,
        JSON.stringify({
          model: "benchmark-chat",
          messages: [{ role: "user", content: "hello" }],
        }),
        gateway,
      ),
      "mixed gateway",
    );
  }
  const control = { headers: adminHeaders(data.token) };
  assertOk(
    http.get(`${baseUrl}/api/v1/usage/summary?window=30d`, control),
    "mixed control plane",
  );
}
