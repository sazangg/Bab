import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import {
  useCreateLimitPolicyApiV1LimitPoliciesPost,
  useDeactivateLimitPolicyApiV1LimitPoliciesPolicyIdDelete,
  useListLimitPoliciesApiV1LimitPoliciesGet,
  useUpdateLimitPolicyApiV1LimitPoliciesPolicyIdPatch,
} from "@/shared/api/generated/limit-policies/limit-policies";
import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type { LimitPolicyResponse } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";

const scopeTypes = ["org", "project", "provider", "provider_model", "virtual_key"] as const;
const metrics = ["request_count", "token_count"] as const;
const windows = ["minute", "day"] as const;

const limitPolicySchema = z.object({
  scope_type: z.enum(scopeTypes),
  scope_id: z.string().min(1),
  scope_value: z.string().optional(),
  metric: z.enum(metrics),
  window: z.enum(windows),
  limit_value: z.coerce.number().int().positive(),
});

type LimitPolicyFormInput = z.input<typeof limitPolicySchema>;
type LimitPolicyFormValues = z.output<typeof limitPolicySchema>;

export function LimitsPage() {
  const queryClient = useQueryClient();
  const policiesQuery = useListLimitPoliciesApiV1LimitPoliciesGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const policies = policiesQuery.data?.status === 200 ? policiesQuery.data.data : [];
  const providers = useMemo(
    () => (providersQuery.data?.status === 200 ? providersQuery.data.data : []),
    [providersQuery.data],
  );
  const projects = useMemo(
    () => (projectsQuery.data?.status === 200 ? projectsQuery.data.data : []),
    [projectsQuery.data],
  );
  const orgId = projects[0]?.org_id ?? providers[0]?.org_id ?? policies[0]?.org_id ?? "";
  const form = useForm<LimitPolicyFormInput, unknown, LimitPolicyFormValues>({
    resolver: zodResolver(limitPolicySchema),
    defaultValues: {
      scope_type: "org",
      scope_id: orgId,
      scope_value: "",
      metric: "request_count",
      window: "minute",
      limit_value: 60,
    },
  });
  const selectedScopeType = useWatch({ control: form.control, name: "scope_type" });
  const createMutation = useCreateLimitPolicyApiV1LimitPoliciesPost({
    mutation: {
      onSuccess: async () => {
        form.reset({
          scope_type: "org",
          scope_id: orgId,
          scope_value: "",
          metric: "request_count",
          window: "minute",
          limit_value: 60,
        });
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateMutation = useUpdateLimitPolicyApiV1LimitPoliciesPolicyIdPatch({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateMutation = useDeactivateLimitPolicyApiV1LimitPoliciesPolicyIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
    },
  });

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-muted-foreground">Governance</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Limit policies</h1>
      </header>

      <section className="rounded-lg border bg-card p-5">
        <div className="mb-5">
          <h2 className="text-base font-semibold">Create policy</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Policies are evaluated at proxy time. Every matching active policy must allow the
            request.
          </p>
        </div>
        <form
          className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]"
          onSubmit={form.handleSubmit((values) =>
            createMutation.mutate({
              data: {
                scope_type: values.scope_type,
                scope_id: values.scope_id,
                scope_value:
                  values.scope_type === "provider_model" ? values.scope_value || null : null,
                metric: values.metric,
                window: values.window,
                limit_value: values.limit_value,
              },
            }),
          )}
        >
          <label className="block text-sm font-medium">
            Scope
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              {...form.register("scope_type", {
                onChange: (event) => {
                  const nextScopeType = event.target.value;
                  form.setValue(
                    "scope_id",
                    defaultScopeId(nextScopeType, orgId, projects, providers),
                  );
                  form.setValue("scope_value", "");
                },
              })}
            >
              {scopeTypes.map((scopeType) => (
                <option key={scopeType} value={scopeType}>
                  {scopeLabel(scopeType)}
                </option>
              ))}
            </select>
          </label>
          <ScopeSelector
            scopeType={selectedScopeType}
            orgId={orgId}
            projects={projects}
            providers={providers}
            value={useWatch({ control: form.control, name: "scope_id" })}
            onChange={(value) => form.setValue("scope_id", value)}
          />
          <label className="block text-sm font-medium">
            Provider model
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none disabled:bg-muted focus:ring-2 focus:ring-ring"
              disabled={selectedScopeType !== "provider_model"}
              placeholder="gpt-5.4-mini"
              {...form.register("scope_value")}
            />
          </label>
          <Select label="Metric" values={metrics} registration={form.register("metric")} />
          <Select label="Window" values={windows} registration={form.register("window")} />
          <label className="block text-sm font-medium">
            Limit
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              type="number"
              min={1}
              {...form.register("limit_value")}
            />
          </label>
          <div className="flex items-end">
            <Button type="submit" disabled={!orgId || createMutation.isPending}>
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
        {Object.values(form.formState.errors)[0]?.message ? (
          <p className="mt-3 text-sm text-destructive">
            {Object.values(form.formState.errors)[0]?.message}
          </p>
        ) : null}
        {createMutation.isError ? (
          <p className="mt-3 text-sm text-destructive">Limit policy was not created.</p>
        ) : null}
      </section>

      <section className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Scope</th>
              <th className="px-3 py-2 font-medium">Target</th>
              <th className="px-3 py-2 font-medium">Metric</th>
              <th className="px-3 py-2 font-medium">Window</th>
              <th className="px-3 py-2 font-medium">Limit</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {policies.map((policy) => (
              <PolicyRow
                key={policy.id}
                policy={policy}
                targetLabel={targetLabel(policy, orgId, projects, providers)}
                onToggle={() =>
                  updateMutation.mutate({
                    policyId: policy.id,
                    data: { is_active: !policy.is_active },
                  })
                }
                onDeactivate={() => {
                  if (window.confirm("Deactivate this limit policy?")) {
                    deactivateMutation.mutate({ policyId: policy.id });
                  }
                }}
              />
            ))}
            {policies.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-muted-foreground" colSpan={7}>
                  No limit policies yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function ScopeSelector({
  scopeType,
  orgId,
  projects,
  providers,
  value,
  onChange,
}: {
  scopeType: string;
  orgId: string;
  projects: { id: string; name: string }[];
  providers: { id: string; name: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  if (scopeType === "org") {
    return <ReadOnlyTarget label="Target" value={orgId} />;
  }

  const options =
    scopeType === "project"
      ? projects
      : scopeType === "provider" || scopeType === "provider_model"
        ? providers
        : [];

  if (scopeType === "virtual_key") {
    return (
      <label className="block text-sm font-medium">
        Virtual key id
        <input
          className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }

  return (
    <label className="block text-sm font-medium">
      Target
      <select
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Select target</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function ReadOnlyTarget({ label, value }: { label: string; value: string }) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-muted px-3 text-sm text-muted-foreground"
        readOnly
        value={value}
      />
    </label>
  );
}

function Select({
  label,
  values,
  registration,
}: {
  label: string;
  values: readonly string[];
  registration: UseFormRegisterReturn;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        {...registration}
      >
        {values.map((value) => (
          <option key={value} value={value}>
            {value.replace("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}

function PolicyRow({
  policy,
  targetLabel,
  onToggle,
  onDeactivate,
}: {
  policy: LimitPolicyResponse;
  targetLabel: string;
  onToggle: () => void;
  onDeactivate: () => void;
}) {
  return (
    <tr className="border-t">
      <td className="px-3 py-2">{scopeLabel(policy.scope_type)}</td>
      <td className="px-3 py-2 text-muted-foreground">{targetLabel}</td>
      <td className="px-3 py-2">{policy.metric.replace("_", " ")}</td>
      <td className="px-3 py-2">{policy.window}</td>
      <td className="px-3 py-2">{policy.limit_value}</td>
      <td className="px-3 py-2">{policy.is_active ? "Active" : "Inactive"}</td>
      <td className="flex gap-2 px-3 py-2">
        <Button type="button" variant="outline" onClick={onToggle}>
          {policy.is_active ? "Pause" : "Activate"}
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={!policy.is_active}
          onClick={onDeactivate}
        >
          Deactivate
        </Button>
      </td>
    </tr>
  );
}

function defaultScopeId(
  scopeType: string,
  orgId: string,
  projects: { id: string }[],
  providers: { id: string }[],
) {
  if (scopeType === "org") {
    return orgId;
  }
  if (scopeType === "project") {
    return projects[0]?.id ?? "";
  }
  if (scopeType === "provider" || scopeType === "provider_model") {
    return providers[0]?.id ?? "";
  }
  return "";
}

function targetLabel(
  policy: LimitPolicyResponse,
  orgId: string,
  projects: { id: string; name: string }[],
  providers: { id: string; name: string }[],
) {
  if (policy.scope_type === "org") {
    return policy.scope_id === orgId ? "Organization" : (policy.scope_id ?? "");
  }
  if (policy.scope_type === "project") {
    return (
      projects.find((project) => project.id === policy.scope_id)?.name ?? policy.scope_id ?? ""
    );
  }
  if (policy.scope_type === "provider" || policy.scope_type === "provider_model") {
    const provider = providers.find((item) => item.id === policy.scope_id)?.name ?? policy.scope_id;
    return policy.scope_value ? `${provider} / ${policy.scope_value}` : (provider ?? "");
  }
  return policy.scope_id ?? "";
}

function scopeLabel(scopeType: string) {
  return scopeType.replace("_", " ");
}
