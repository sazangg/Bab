import { zodResolver } from "@hookform/resolvers/zod";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Gauge, Layers3, Pencil, Plus, X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  useCreateAllocationApiV1ProjectsAllocationsPost,
  useListProjectAllocationUsageApiV1ProjectsProjectIdAllocationsUsageGet,
  useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet,
  useUpdateAllocationApiV1ProjectsAllocationsAllocationIdPatch,
} from "@/shared/api/generated/projects/projects";
import {
  listCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  listModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";
import {
  useListTeamAllocationUsageApiV1TeamsTeamIdAllocationsUsageGet,
  useListTeamAllocationsApiV1TeamsTeamIdAllocationsGet,
} from "@/shared/api/generated/teams/teams";
import type {
  AllocationResponse,
  AllocationUsageSummary,
  CredentialPoolResponse,
  ModelOfferingResponse,
  UsageBreakdownRow,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge } from "@/shared/components/StatusBadge";

const allocationSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(1000).optional(),
  provider_id: z.string().min(1),
  pool_id: z.string().min(1),
  model_offering_ids: z.array(z.string()).min(1, "Select at least one model"),
  budget_dollars: z.preprocess(optionalNumber, z.number().min(0).optional()),
  max_requests: z.preprocess(optionalNumber, z.number().int().min(1).optional()),
  max_input_tokens: z.preprocess(optionalNumber, z.number().int().min(1).optional()),
  max_output_tokens: z.preprocess(optionalNumber, z.number().int().min(1).optional()),
  max_tokens_per_request: z.preprocess(optionalNumber, z.number().int().min(1).optional()),
  window: z.enum(["daily", "weekly", "monthly", "lifetime"]),
  is_default: z.boolean(),
  is_active: z.boolean(),
});

type AllocationInput = z.input<typeof allocationSchema>;
type AllocationValues = z.output<typeof allocationSchema>;

type AllocationTarget =
  | { type: "team"; teamId: string; title?: string }
  | { type: "project"; projectId: string; teamId: string; title?: string };

export function AllocationManagementSection({ target }: { target: AllocationTarget }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editingAllocation, setEditingAllocation] = useState<AllocationResponse | null>(null);
  const teamAllocationsQuery = useListTeamAllocationsApiV1TeamsTeamIdAllocationsGet(
    target.type === "team" ? target.teamId : target.teamId,
    { query: { enabled: Boolean(target.teamId) } },
  );
  const projectAllocationsQuery = useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet(
    target.type === "project" ? target.projectId : "",
    { query: { enabled: target.type === "project" && Boolean(target.projectId) } },
  );
  const teamUsageQuery = useListTeamAllocationUsageApiV1TeamsTeamIdAllocationsUsageGet(
    target.type === "team" ? target.teamId : target.teamId,
    { query: { enabled: Boolean(target.teamId) } },
  );
  const projectUsageQuery = useListProjectAllocationUsageApiV1ProjectsProjectIdAllocationsUsageGet(
    target.type === "project" ? target.projectId : "",
    { query: { enabled: target.type === "project" && Boolean(target.projectId) } },
  );
  const allocations =
    target.type === "project"
      ? projectAllocationsQuery.data?.status === 200
        ? projectAllocationsQuery.data.data
        : []
      : teamAllocationsQuery.data?.status === 200
        ? teamAllocationsQuery.data.data
        : [];
  const teamAllocations =
    teamAllocationsQuery.data?.status === 200 ? teamAllocationsQuery.data.data : [];
  const usageSummaries =
    target.type === "project"
      ? projectUsageQuery.data?.status === 200
        ? projectUsageQuery.data.data
        : []
      : teamUsageQuery.data?.status === 200
        ? teamUsageQuery.data.data
        : [];
  const usageByAllocationId = new Map(
    usageSummaries.map((summary) => [summary.allocation_id, summary]),
  );
  const teamDefault = teamAllocations.find((allocation) => allocation.is_default);
  const isLoading =
    target.type === "project" ? projectAllocationsQuery.isPending : teamAllocationsQuery.isPending;
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const configuredProviders = providers.filter(
    (provider) => (provider.credential_summary?.active ?? 0) > 0,
  );
  const poolQueries = useQueries({
    queries: configuredProviders.map((provider) => ({
      queryKey: ["allocation-card-pools", provider.id],
      queryFn: () => listCredentialPoolsApiV1ProvidersProviderIdPoolsGet(provider.id),
    })),
  });
  const modelQueries = useQueries({
    queries: configuredProviders.map((provider) => ({
      queryKey: ["allocation-card-models", provider.id],
      queryFn: () =>
        listModelOfferingsApiV1ProvidersProviderIdOfferingsGet(provider.id, { limit: 100 }),
    })),
  });
  const poolsById = useMemo(() => {
    const map = new Map<string, CredentialPoolResponse>();
    poolQueries.forEach((query) => {
      if (query.data?.status === 200) {
        query.data.data.forEach((pool) => map.set(pool.id, pool));
      }
    });
    return map;
  }, [poolQueries]);
  const modelsById = useMemo(() => {
    const map = new Map<string, ModelOfferingResponse>();
    modelQueries.forEach((query) => {
      if (query.data?.status === 200) {
        query.data.data.items.forEach((model) => map.set(model.id, model));
      }
    });
    return map;
  }, [modelQueries]);

  const createAllocation = useCreateAllocationApiV1ProjectsAllocationsPost({
    mutation: {
      onSuccess: async () => {
        setOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateAllocation = useUpdateAllocationApiV1ProjectsAllocationsAllocationIdPatch({
    mutation: {
      onSuccess: async () => {
        setOpen(false);
        setEditingAllocation(null);
        await queryClient.invalidateQueries();
      },
    },
  });

  const openCreateSheet = () => {
    setEditingAllocation(null);
    setOpen(true);
  };

  const openEditSheet = (allocation: AllocationResponse) => {
    setEditingAllocation(allocation);
    setOpen(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{target.title ?? "Allocations"}</CardTitle>
        <CardDescription>
          {target.type === "project"
            ? teamDefault
              ? `Team default: ${teamDefault.name}. Runtime enforcement checks both team and project limits.`
              : "No team allocation exists. A project allocation can define the effective access."
            : "Define the team-level default that projects inherit."}
        </CardDescription>
        <CardAction>
          <Button size="sm" onClick={openCreateSheet}>
            <Plus />
            New allocation
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading allocations...</p>
        ) : allocations.length === 0 ? (
          <EmptyState
            icon={Layers3}
            title="No allocations yet"
            description="Create an allocation to grant access to credential pools and models."
          />
        ) : (
          <div className="grid gap-3">
            {allocations.map((allocation) => (
              <AllocationCard
                key={allocation.id}
                allocation={allocation}
                poolsById={poolsById}
                modelsById={modelsById}
                usage={usageByAllocationId.get(allocation.id)}
                onEdit={() => openEditSheet(allocation)}
              />
            ))}
          </div>
        )}
      </CardContent>
      <AllocationSheet
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) setEditingAllocation(null);
        }}
        allocation={editingAllocation}
        modelsById={modelsById}
        isPending={createAllocation.isPending || updateAllocation.isPending}
        onSubmit={(values) => {
          const data = {
            name: values.name,
            description: values.description?.trim() ? values.description : null,
            offerings: [
              ...values.model_offering_ids.map((modelOfferingId) => ({
                pool_id: values.pool_id,
                model_offering_id: modelOfferingId,
              })),
            ],
            budget_cents:
              values.budget_dollars === undefined ? null : Math.round(values.budget_dollars * 100),
            max_requests: values.max_requests ?? null,
            max_input_tokens: values.max_input_tokens ?? null,
            max_output_tokens: values.max_output_tokens ?? null,
            max_tokens_per_request: values.max_tokens_per_request ?? null,
            window: values.window,
            is_default: values.is_default,
            is_active: values.is_active,
          };
          if (editingAllocation) {
            updateAllocation.mutate({ allocationId: editingAllocation.id, data });
            return;
          }
          createAllocation.mutate({
            data: {
              ...data,
              team_id: target.type === "team" ? target.teamId : undefined,
              project_id: target.type === "project" ? target.projectId : undefined,
            },
          });
        }}
      />
    </Card>
  );
}

function AllocationCard({
  allocation,
  poolsById,
  modelsById,
  usage,
  onEdit,
}: {
  allocation: AllocationResponse;
  poolsById: Map<string, CredentialPoolResponse>;
  modelsById: Map<string, ModelOfferingResponse>;
  usage: AllocationUsageSummary | undefined;
  onEdit: () => void;
}) {
  const offeringLabels = allocation.offerings.map((offering) => {
    const pool = poolsById.get(offering.pool_id);
    const model = modelsById.get(offering.model_offering_id);
    return {
      key: `${offering.pool_id}-${offering.model_offering_id}`,
      pool: pool?.name ?? "Unknown pool",
      model: model?.alias
        ? `${model.alias} (${model.provider_model_name})`
        : (model?.provider_model_name ?? "Unknown model"),
    };
  });
  return (
    <div className="rounded-md border p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-medium">{allocation.name}</h3>
            {allocation.is_default ? <StatusBadge variant="active">Default</StatusBadge> : null}
            <StatusBadge variant={allocation.is_active ? "active" : "inactive"}>
              {allocation.is_active ? "Active" : "Inactive"}
            </StatusBadge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {allocation.description || "No description"}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onEdit}>
          <Pencil data-icon="inline-start" />
          Edit
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {offeringLabels.map((offering) => (
          <span
            key={offering.key}
            className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-1 text-xs"
          >
            {offering.model}
            <span className="text-muted-foreground">via {offering.pool}</span>
          </span>
        ))}
      </div>
      <div className="mt-3 grid gap-2 text-xs text-muted-foreground md:grid-cols-4">
        <span>Budget: {formatCents(allocation.budget_cents)}</span>
        <span>Requests: {allocation.max_requests?.toLocaleString() ?? "No cap"}</span>
        <span>Input tokens: {allocation.max_input_tokens?.toLocaleString() ?? "No cap"}</span>
        <span>Window: {allocation.window}</span>
      </div>
      <AllocationUsagePanel allocation={allocation} usage={usage} />
    </div>
  );
}

function AllocationUsagePanel({
  allocation,
  usage,
}: {
  allocation: AllocationResponse;
  usage: AllocationUsageSummary | undefined;
}) {
  const totals = usage?.totals;
  const requests = totals?.requests ?? 0;
  const promptTokens = totals?.prompt_tokens ?? 0;
  const completionTokens = totals?.completion_tokens ?? 0;
  const totalTokens = totals?.total_tokens ?? 0;
  const costCents = totals?.cost_cents ?? 0;
  const failedRequests = totals?.failed_requests ?? 0;
  const successfulRequests = totals?.successful_requests ?? 0;
  const averageLatency = totals?.average_latency_ms ?? null;
  const pressureItems = [
    {
      label: "Budget",
      used: costCents,
      cap: allocation.budget_cents,
      usedLabel: formatCents(costCents),
      capLabel: formatCents(allocation.budget_cents),
    },
    {
      label: "Requests",
      used: requests,
      cap: allocation.max_requests,
      usedLabel: requests.toLocaleString(),
      capLabel: allocation.max_requests?.toLocaleString() ?? "No cap",
    },
    {
      label: "Input tokens",
      used: promptTokens,
      cap: allocation.max_input_tokens,
      usedLabel: promptTokens.toLocaleString(),
      capLabel: allocation.max_input_tokens?.toLocaleString() ?? "No cap",
    },
    {
      label: "Output tokens",
      used: completionTokens,
      cap: allocation.max_output_tokens,
      usedLabel: completionTokens.toLocaleString(),
      capLabel: allocation.max_output_tokens?.toLocaleString() ?? "No cap",
    },
  ];
  const constrainedItems = pressureItems.filter(
    (item) => item.cap !== null && item.cap !== undefined,
  );
  const windowLabel = formatWindowLabel(usage?.window || allocation.window);
  const hottestItem = constrainedItems
    .map((item) => ({ ...item, ratio: item.cap ? item.used / item.cap : 0 }))
    .sort((left, right) => right.ratio - left.ratio)[0];
  const pressureState = getPressureState(hottestItem?.ratio ?? 0);

  if (!usage || requests === 0) {
    return (
      <div className="mt-4 rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <Gauge className="size-4" />
          No usage recorded for this allocation yet.
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-3 rounded-md border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-background p-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Gauge className="size-4 text-muted-foreground" />
            Allocation pressure
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {hottestItem
              ? `${hottestItem.label} is the closest active constraint in the ${windowLabel} window.`
              : `No request, token, or budget cap is set for this ${windowLabel} allocation.`}
          </p>
        </div>
        <StatusBadge variant={pressureState.variant}>{pressureState.label}</StatusBadge>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {pressureItems.map((item) => (
          <PressureMeter key={item.label} {...item} />
        ))}
      </div>
      <div className="grid gap-2 text-sm md:grid-cols-5">
        <UsageMetric label="Requests" value={requests.toLocaleString()} />
        <UsageMetric
          label="Tokens"
          value={totalTokens.toLocaleString()}
          detail={`${promptTokens.toLocaleString()} in / ${completionTokens.toLocaleString()} out`}
        />
        <UsageMetric label="Spend" value={formatCents(costCents)} />
        <UsageMetric
          label="Errors"
          value={failedRequests.toLocaleString()}
          detail={`${successfulRequests.toLocaleString()} successful`}
        />
        <UsageMetric
          label="Latency"
          value={averageLatency === null ? "-" : `${averageLatency}ms`}
        />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <BreakdownList title="Virtual key drivers" rows={usage.by_virtual_key} />
        <BreakdownList title="Model drivers" rows={usage.by_model} />
        <BreakdownList title="Pool drivers" rows={usage.by_pool} />
        <BreakdownList title="Provider drivers" rows={usage.by_provider} />
      </div>
      <div className="flex items-start gap-2 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
        <div>
          Remaining: {formatRemaining(requests, allocation.max_requests)} requests,
          {formatRemaining(costCents, allocation.budget_cents)} budget in the {windowLabel} window.
          Token pressure uses recorded input/output tokens for that same window.
        </div>
      </div>
    </div>
  );
}

function PressureMeter({
  label,
  used,
  cap,
  usedLabel,
  capLabel,
}: {
  label: string;
  used: number;
  cap: number | null | undefined;
  usedLabel: string;
  capLabel: string;
}) {
  const percent = cap ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  const state = getPressureState(cap ? used / cap : 0);

  return (
    <div className="rounded-md bg-background p-3">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{label}</span>
        <span className={state.textClass}>{cap ? `${percent}%` : "Uncapped"}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${state.barClass}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{usedLabel}</span>
        <span>{capLabel}</span>
      </div>
    </div>
  );
}

function UsageMetric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-md bg-background p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
      {detail ? <div className="mt-0.5 text-xs text-muted-foreground">{detail}</div> : null}
    </div>
  );
}

function BreakdownList({ title, rows }: { title: string; rows: UsageBreakdownRow[] }) {
  const maxRequests = Math.max(...rows.map((row) => row.requests ?? 0), 0);

  return (
    <div className="rounded-md bg-background p-2">
      <div className="mb-2 text-xs font-medium text-muted-foreground">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-muted-foreground">No usage</div>
      ) : (
        <div className="space-y-1.5">
          {rows.slice(0, 5).map((row) => (
            <div key={row.id} className="space-y-1 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate">{row.label}</span>
                <span className="shrink-0 text-muted-foreground">
                  {(row.requests ?? 0).toLocaleString()} req ·{" "}
                  {(row.total_tokens ?? 0).toLocaleString()} tok
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary/70"
                  style={{
                    width: `${maxRequests ? Math.max(4, ((row.requests ?? 0) / maxRequests) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AllocationSheet({
  open,
  onOpenChange,
  allocation,
  modelsById,
  isPending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  allocation: AllocationResponse | null;
  modelsById: Map<string, ModelOfferingResponse>;
  isPending: boolean;
  onSubmit: (values: AllocationValues) => void;
}) {
  const form = useForm<AllocationInput, unknown, AllocationValues>({
    resolver: zodResolver(allocationSchema),
    defaultValues: {
      name: "",
      description: "",
      provider_id: "",
      pool_id: "",
      model_offering_ids: [],
      budget_dollars: undefined,
      max_requests: undefined,
      max_input_tokens: undefined,
      max_output_tokens: undefined,
      max_tokens_per_request: undefined,
      window: "monthly",
    },
  });
  const providerId = useWatch({ control: form.control, name: "provider_id" });
  const poolId = useWatch({ control: form.control, name: "pool_id" });
  const modelOfferingIds = useWatch({ control: form.control, name: "model_offering_ids" }) ?? [];
  const window = useWatch({ control: form.control, name: "window" });
  const isDefault = useWatch({ control: form.control, name: "is_default" });
  const isActive = useWatch({ control: form.control, name: "is_active" });
  const initializedFor = useRef<string | null>(null);
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(providerId || "", {
    query: { enabled: Boolean(providerId) },
  });
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(
    providerId || "",
    { limit: 100 },
    { query: { enabled: Boolean(providerId) } },
  );
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data.items : [];
  const configuredProviders = providers.filter(
    (provider) => (provider.credential_summary?.active ?? 0) > 0,
  );
  const activePools = pools.filter(
    (pool) => pool.is_active && (pool.active_credential_count ?? 0) > 0,
  );
  const activeModels = models.filter((model) => model.is_active);
  const selectedModels = activeModels.filter((model) => modelOfferingIds.includes(model.id));

  useEffect(() => {
    if (!open) {
      initializedFor.current = null;
      return;
    }
    const resetKey = allocation ? `edit-${allocation.id}` : "create";
    if (initializedFor.current === resetKey) return;
    if (allocation) {
      const firstOffering = allocation.offerings[0];
      const firstModel = firstOffering ? modelsById.get(firstOffering.model_offering_id) : null;
      if (firstOffering && !firstModel) return;
      initializedFor.current = resetKey;
      form.reset({
        name: allocation.name,
        description: allocation.description ?? "",
        provider_id: firstModel?.provider_id ?? "",
        pool_id: firstOffering?.pool_id ?? "",
        model_offering_ids: allocation.offerings.map((offering) => offering.model_offering_id),
        budget_dollars:
          allocation.budget_cents === null || allocation.budget_cents === undefined
            ? undefined
            : allocation.budget_cents / 100,
        max_requests: allocation.max_requests ?? undefined,
        max_input_tokens: allocation.max_input_tokens ?? undefined,
        max_output_tokens: allocation.max_output_tokens ?? undefined,
        max_tokens_per_request: allocation.max_tokens_per_request ?? undefined,
        window: toAllocationWindow(allocation.window),
        is_default: allocation.is_default,
        is_active: allocation.is_active,
      });
      return;
    }
    initializedFor.current = resetKey;
    form.reset({
      name: "",
      description: "",
      provider_id: "",
      pool_id: "",
      model_offering_ids: [],
      budget_dollars: undefined,
      max_requests: undefined,
      max_input_tokens: undefined,
      max_output_tokens: undefined,
      max_tokens_per_request: undefined,
      window: "monthly",
      is_default: true,
      is_active: true,
    });
  }, [open, allocation, form, modelsById]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{allocation ? "Edit allocation" : "New allocation"}</SheetTitle>
          <SheetDescription>
            Define the pool, model access, and limits that virtual keys can consume.
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1">
          <form className="flex flex-col gap-5 px-6 py-5" onSubmit={form.handleSubmit(onSubmit)}>
            <section className="rounded-md border p-4">
              <div className="mb-4">
                <h3 className="text-sm font-medium">Basics</h3>
                <p className="text-xs text-muted-foreground">
                  Name the allocation so it is recognizable from teams, projects, and keys.
                </p>
              </div>
              <div className="grid gap-3">
                <Field label="Name" htmlFor="allocation-name">
                  <Input id="allocation-name" autoFocus {...form.register("name")} />
                </Field>
                <Field label="Description" htmlFor="allocation-description">
                  <Textarea
                    id="allocation-description"
                    className="min-h-24"
                    {...form.register("description")}
                  />
                </Field>
              </div>
            </section>

            <section className="rounded-md border p-4">
              <div className="mb-4">
                <h3 className="text-sm font-medium">Routing access</h3>
                <p className="text-xs text-muted-foreground">
                  Pick a configured provider, one active credential pool, and the models this
                  allocation can route to.
                </p>
              </div>
              <div className="grid gap-4">
                <div className="flex flex-col gap-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <Field label="Provider">
                      <Select
                        value={providerId || ""}
                        onValueChange={(value) => {
                          form.setValue("provider_id", value, { shouldDirty: true });
                          form.setValue("pool_id", "", { shouldDirty: true });
                          form.setValue("model_offering_ids", [], { shouldDirty: true });
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select provider" />
                        </SelectTrigger>
                        <SelectContent>
                          {configuredProviders.map((provider) => (
                            <SelectItem key={provider.id} value={provider.id}>
                              {provider.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Credential pool">
                      <Select
                        value={poolId || ""}
                        onValueChange={(value) =>
                          form.setValue("pool_id", value, { shouldDirty: true })
                        }
                        disabled={!providerId}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select pool" />
                        </SelectTrigger>
                        <SelectContent>
                          {activePools.map((pool) => (
                            <SelectItem key={pool.id} value={pool.id}>
                              {pool.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {providerId && activePools.length === 0 ? (
                        <p className="text-xs text-muted-foreground">
                          This provider has no active pool with active credentials.
                        </p>
                      ) : null}
                    </Field>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {selectedModels.length} model{selectedModels.length === 1 ? "" : "s"} selected
                    {poolId ? " for the selected pool." : "."}
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <Label>Model offerings</Label>
                  <div className="rounded-md border">
                    <ScrollArea className="h-72">
                      <div className="grid gap-1 p-2 md:grid-cols-2">
                        {!providerId ? (
                          <p className="p-2 text-sm text-muted-foreground md:col-span-2">
                            Select a provider to see active models.
                          </p>
                        ) : activeModels.length === 0 ? (
                          <p className="p-2 text-sm text-muted-foreground md:col-span-2">
                            No active models for this provider.
                          </p>
                        ) : (
                          activeModels.map((model) => {
                            const checked = modelOfferingIds.includes(model.id);
                            return (
                              <label
                                key={model.id}
                                className="flex min-w-0 cursor-pointer items-start gap-3 rounded-md px-2 py-2 hover:bg-muted/50"
                              >
                                <Checkbox
                                  checked={checked}
                                  onCheckedChange={(nextChecked) => {
                                    const nextIds = nextChecked
                                      ? [...modelOfferingIds, model.id]
                                      : modelOfferingIds.filter((id) => id !== model.id);
                                    form.setValue("model_offering_ids", nextIds, {
                                      shouldDirty: true,
                                      shouldValidate: true,
                                    });
                                  }}
                                />
                                <span className="min-w-0 break-words">
                                  <span className="block text-sm leading-5 font-medium break-words">
                                    {model.alias || model.provider_model_name}
                                  </span>
                                  <span className="block text-xs leading-4 break-all text-muted-foreground">
                                    {model.provider_model_name}
                                  </span>
                                </span>
                              </label>
                            );
                          })
                        )}
                      </div>
                    </ScrollArea>
                  </div>
                  {selectedModels.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedModels.map((model) => (
                        <Button
                          key={model.id}
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            form.setValue(
                              "model_offering_ids",
                              modelOfferingIds.filter((id) => id !== model.id),
                              { shouldDirty: true, shouldValidate: true },
                            )
                          }
                        >
                          {model.alias || model.provider_model_name}
                          <X data-icon="inline-end" />
                        </Button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="rounded-md border p-4">
              <div className="mb-4">
                <h3 className="text-sm font-medium">State</h3>
                <p className="text-xs text-muted-foreground">
                  Defaults are inherited by virtual keys unless a key has a custom allocation.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <SwitchField
                  label="Default allocation"
                  description="Use as the default allocation for this target."
                  checked={isDefault}
                  onCheckedChange={(checked) =>
                    form.setValue("is_default", checked, { shouldDirty: true })
                  }
                />
                <SwitchField
                  label="Active"
                  description="Inactive allocations cannot be used for routing."
                  checked={isActive}
                  onCheckedChange={(checked) =>
                    form.setValue("is_active", checked, { shouldDirty: true })
                  }
                />
              </div>
            </section>

            <section className="rounded-md border p-4">
              <div className="mb-4">
                <h3 className="text-sm font-medium">Limits</h3>
                <p className="text-xs text-muted-foreground">
                  Leave a field blank when this allocation should not enforce that cap.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <NumberField label="Budget ($)" name="budget_dollars" form={form} step="0.01" />
                <Field label="Window">
                  <ToggleGroup
                    type="single"
                    value={window || "monthly"}
                    onValueChange={(value) => {
                      if (value) form.setValue("window", value as AllocationValues["window"]);
                    }}
                    variant="outline"
                    size="sm"
                    className="flex-wrap"
                  >
                    <ToggleGroupItem value="daily">Daily</ToggleGroupItem>
                    <ToggleGroupItem value="weekly">Weekly</ToggleGroupItem>
                    <ToggleGroupItem value="monthly">Monthly</ToggleGroupItem>
                    <ToggleGroupItem value="lifetime">Lifetime</ToggleGroupItem>
                  </ToggleGroup>
                </Field>
                <NumberField label="Max requests" name="max_requests" form={form} />
                <NumberField label="Max tokens/request" name="max_tokens_per_request" form={form} />
                <NumberField label="Input tokens" name="max_input_tokens" form={form} />
                <NumberField label="Output tokens" name="max_output_tokens" form={form} />
              </div>
            </section>
          </form>
        </ScrollArea>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Saving..." : allocation ? "Save allocation" : "Create allocation"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function NumberField({
  label,
  name,
  form,
  step,
}: {
  label: string;
  name:
    | "max_requests"
    | "max_input_tokens"
    | "max_output_tokens"
    | "max_tokens_per_request"
    | "budget_dollars";
  form: ReturnType<typeof useForm<AllocationInput, unknown, AllocationValues>>;
  step?: string;
}) {
  return (
    <Field label={label} htmlFor={`allocation-${name}`}>
      <Input id={`allocation-${name}`} type="number" step={step} {...form.register(name)} />
    </Field>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function SwitchField({
  label,
  description,
  checked,
  onCheckedChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border bg-muted/20 p-3">
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

function optionalNumber(value: unknown) {
  return value === "" || value === null || value === undefined ? undefined : Number(value);
}

function toAllocationWindow(value: string): AllocationValues["window"] {
  return value === "daily" || value === "weekly" || value === "monthly" || value === "lifetime"
    ? value
    : "monthly";
}

function formatCents(value: number | null | undefined) {
  return value == null ? "No cap" : `$${(value / 100).toLocaleString()}`;
}

function formatRemaining(used: number, cap: number | null | undefined) {
  if (cap == null) return "no cap";
  return Math.max(0, cap - used).toLocaleString();
}

function formatWindowLabel(window: string) {
  return window === "lifetime" ? "lifetime" : window;
}

function getPressureState(ratio: number): {
  label: string;
  variant: "active" | "expired";
  barClass: string;
  textClass: string;
} {
  if (ratio >= 0.9) {
    return {
      label: "High pressure",
      variant: "expired",
      barClass: "bg-destructive",
      textClass: "text-destructive",
    };
  }
  if (ratio >= 0.7) {
    return {
      label: "Watch",
      variant: "expired",
      barClass: "bg-amber-500",
      textClass: "text-amber-700",
    };
  }
  return {
    label: "Healthy",
    variant: "active",
    barClass: "bg-primary",
    textClass: "text-muted-foreground",
  };
}
