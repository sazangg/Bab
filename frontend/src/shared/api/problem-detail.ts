import { isAxiosError } from "axios";

export function getProblemDetail(error: unknown, fallback: string) {
  if (!isAxiosError(error)) return fallback;
  const detail = error.response?.data?.detail;
  if (typeof detail === "string" && detail.length > 0) return detail;
  if (
    detail &&
    typeof detail === "object" &&
    "message" in detail &&
    typeof detail.message === "string"
  ) {
    return detail.message;
  }
  return fallback;
}
