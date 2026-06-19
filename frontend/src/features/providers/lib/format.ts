import type { ProviderModelOfferingResponse } from "@/shared/api/generated/schemas";

import { modelCapabilityOptions, routingPolicyOptions } from "./schemas";

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

const RELATIVE_TIME_UNITS: Array<{ unit: Intl.RelativeTimeFormatUnit; seconds: number }> = [
  { unit: "year", seconds: 60 * 60 * 24 * 365 },
  { unit: "month", seconds: 60 * 60 * 24 * 30 },
  { unit: "day", seconds: 60 * 60 * 24 },
  { unit: "hour", seconds: 60 * 60 },
  { unit: "minute", seconds: 60 },
  { unit: "second", seconds: 1 },
];

const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function formatRelativeFromNow(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  const deltaSeconds = (date.getTime() - Date.now()) / 1000;
  const absDelta = Math.abs(deltaSeconds);
  for (const { unit, seconds } of RELATIVE_TIME_UNITS) {
    if (absDelta >= seconds || unit === "second") {
      const value = Math.round(deltaSeconds / seconds);
      return relativeTimeFormatter.format(value, unit);
    }
  }
  return "just now";
}

export function formatRoutingPolicy(value: string) {
  return routingPolicyOptions.find((option) => option.value === value)?.label ?? value;
}

export function formatCapability(value: unknown) {
  if (value === true) {
    return "Supported";
  }

  if (value === false) {
    return "Not declared";
  }

  return "Unknown";
}

export function formatTokenPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return "Unset";
  return `${formatCurrency(value / 100)} / 1M`;
}

export function formatPricingSource(value: string | null | undefined) {
  if (value === "manual") return "manual override";
  if (value === "catalog") return "provider catalog";
  return "pricing unset";
}

export function centsToDollars(value: number | null | undefined) {
  return value === null || value === undefined ? undefined : value / 100;
}

export function dollarsToCents(value: number | null | undefined) {
  return value === null || value === undefined ? null : Math.round(value * 100);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 4,
  }).format(value);
}

export function capabilityListToRecord(capabilities: string[]) {
  return Object.fromEntries(
    modelCapabilityOptions.map((item) => [item, capabilities.includes(item)]),
  );
}

export function capabilityRecordToList(capabilities: ProviderModelOfferingResponse["capabilities"]) {
  return modelCapabilityOptions.filter((item) => capabilities?.[item] === true);
}

export function combinedModality(inputModalities: string[], outputModalities: string[]) {
  return Array.from(new Set([...inputModalities, ...outputModalities])).join("+") || "text";
}

export function formatModalities(modalities: string[]) {
  return modalities.length ? modalities.join(", ") : "Unknown";
}

export function sanitizeCredentialValidationMessage(value?: string | null) {
  if (!value) return null;
  if (value.includes("401")) {
    return "The provider rejected this credential. Check the API key and provider account.";
  }
  if (value.includes("403")) {
    return "This credential is not authorized for the provider.";
  }
  if (value.includes("404")) {
    return "The provider models endpoint was not found. Check the provider base URL.";
  }
  if (value.includes("429")) {
    return "The provider rate limit was reached while testing this credential.";
  }
  if (value.includes("timeout") || value.includes("timed out")) {
    return "The provider did not respond before the request timed out.";
  }
  if (/\b5\d\d\b/.test(value)) {
    return "The provider returned a server error while testing this credential.";
  }
  return "Credential validation failed. Check the key and provider settings.";
}
