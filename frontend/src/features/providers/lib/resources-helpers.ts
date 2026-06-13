import { z } from "zod";

import type { StatusVariant } from "@/shared/components/StatusBadge";

import { routingPolicyOptions, type CredentialPoolValues } from "./schemas";

const healthLabels: Record<string, { label: string; variant: StatusVariant }> = {
  valid: { label: "Valid", variant: "active" },
  unchecked: { label: "Untested", variant: "inactive" },
  invalid: { label: "Invalid", variant: "error" },
  degraded: { label: "Degraded", variant: "error" },
};

export function formatHealth(status: string): { label: string; variant: StatusVariant } {
  return healthLabels[status] ?? { label: status, variant: "inactive" };
}

export function formatRoutingPolicy(value: string) {
  return routingPolicyOptions.find((option) => option.value === value)?.label ?? value;
}

export function formatMetadataSource(value: string) {
  if (value === "manual") return "Manual override";
  if (value === "catalog") return "Provider catalog";
  if (value === "provider") return "Provider-reported";
  return value;
}

export function toRoutingPolicyValue(value: string): CredentialPoolValues["selection_policy"] {
  return routingPolicyOptions.some((option) => option.value === value)
    ? (value as CredentialPoolValues["selection_policy"])
    : "priority";
}

export const poolMembershipSchema = z.object({
  provider_credential_id: z.string().min(1),
  priority: z.coerce.number().int().min(0),
  weight: z.coerce.number().int().min(1),
});

export type PoolMembershipInput = z.input<typeof poolMembershipSchema>;
export type PoolMembershipValues = z.output<typeof poolMembershipSchema>;
