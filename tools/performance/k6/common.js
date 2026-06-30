import http from "k6/http";
import { check } from "k6";

export const baseUrl = __ENV.BASE_URL || "http://host.docker.internal:8000";
const runtimeContext = JSON.parse(open("/runtime/context.json"));

export function context() {
  return runtimeContext;
}

export function login(ctx) {
  const response = http.post(
    `${baseUrl}/api/v1/auth/login`,
    JSON.stringify({ email: ctx.admin_email, password: ctx.admin_password }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(response, { "login succeeds": (r) => r.status === 200 });
  return response.json("access_token");
}

export function adminHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

export function gatewayHeaders(ctx) {
  return {
    Authorization: `Bearer ${ctx.virtual_key}`,
    "Content-Type": "application/json",
  };
}

export function assertOk(response, name) {
  check(response, { [`${name} succeeds`]: (r) => r.status === 200 });
}

export function scenarioOptions(duration = "60s") {
  return {
    vus: Number(__ENV.VUS || 1),
    duration: __ENV.DURATION || duration,
    thresholds: { checks: ["rate==1"] },
    summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  };
}
