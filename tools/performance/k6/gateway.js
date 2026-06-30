import http from "k6/http";
import { assertOk, baseUrl, context, gatewayHeaders, scenarioOptions } from "./common.js";

export const options = scenarioOptions();

export function setup() {
  return context();
}

export default function (ctx) {
  const params = { headers: gatewayHeaders(ctx) };
  assertOk(http.get(`${baseUrl}/v1/models`, params), "models");
  assertOk(
    http.post(
      `${baseUrl}/v1/chat/completions`,
      JSON.stringify({
        model: "benchmark-chat",
        messages: [{ role: "user", content: "hello" }],
      }),
      params,
    ),
    "chat completion",
  );
}
