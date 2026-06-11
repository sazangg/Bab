import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

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
import { Textarea } from "@/components/ui/textarea";
import {
  useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost,
  useCreateScopedPolicyAssignmentApiV1PoliciesAssignmentsScopedPolicyPost,
  useDeletePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdDelete,
  useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet,
  useListAccessPoliciesApiV1PoliciesAccessGet,
  useListLimitPoliciesApiV1PoliciesLimitsGet,
  useListPolicyAssignmentsApiV1PoliciesAssignmentsGet,
} from "@/shared/api/generated/policies/policies";
import type {
  AccessPolicyResponse,
  AccessPolicyRouteInput,
  AccessPolicyProviderOption,
  LimitPolicyResponse,
  LimitPolicyRuleInput,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge } from "@/shared/components/StatusBadge";

type ScopeTarget =
  | { type: "team"; teamId: string }
  | { type: "project"; projectId: string; teamId: string }
  | { type: "virtual_key"; projectId: string; virtualKeyId: string };

type SheetKind = "access" | "limit" | null;
type AssignKind = "access" | "limit" | null;
type DraftLimitRule = {
  name: string;
  limitType: string;
  limitValue: string;
  intervalUnit: string;
  intervalCount: string;
};
type DraftAccessRoute = {
  id: string;
  providerId: string;
  providerLabel: string;
  poolId: string;
  poolLabel: string;
  modelIds: string[];
};

const limitTypeOptions = [
  { value: "budget_cents", label: "Spend budget" },
  { value: "requests", label: "Request count" },
  { value: "input_tokens", label: "Input tokens" },
  { value: "output_tokens", label: "Output tokens" },
  { value: "total_tokens", label: "Total tokens" },
  { value: "tokens_per_request", label: "Tokens per request" },
];

export function PolicyScopeSection({
  target,
  canManage,
}: {
  target: ScopeTarget;
  canManage: boolean;
}) {
  const [sheetKind, setSheetKind] = useState<SheetKind>(null);
  const [assignKind, setAssignKind] = useState<AssignKind>(null);
  const queryClient = useQueryClient();
  const accessQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const limitsQuery = useListLimitPoliciesApiV1PoliciesLimitsGet();
  const assignmentsQuery = useListPolicyAssignmentsApiV1PoliciesAssignmentsGet();
  const deleteAssignment = useDeletePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Policy assignment removed.");
        await queryClient.invalidateQueries();
      },
      onError: () => toast.error("Policy assignment could not be removed."),
    },
  });
  const accessPolicies = accessQuery.data?.status === 200 ? accessQuery.data.data : [];
  const limitPolicies = limitsQuery.data?.status === 200 ? limitsQuery.data.data : [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const scopedAssignments = assignments.filter((assignment) => {
    if (target.type === "team") {
      return assignment.scope_type === "team" && assignment.team_id === target.teamId;
    }
    if (target.type === "virtual_key") {
      return (
        assignment.scope_type === "virtual_key" && assignment.virtual_key_id === target.virtualKeyId
      );
    }
    return assignment.scope_type === "project" && assignment.project_id === target.projectId;
  });
  const accessById = new Map(accessPolicies.map((policy) => [policy.id, policy]));
  const limitById = new Map(limitPolicies.map((policy) => [policy.id, policy]));

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Policies</CardTitle>
          <CardDescription>
            Direct assignments for this {target.type}. Higher-scope policies still apply at runtime.
          </CardDescription>
          {canManage ? (
            <CardAction className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setAssignKind("limit")}>
                <Plus />
                Assign limit
              </Button>
              <Button size="sm" variant="outline" onClick={() => setAssignKind("access")}>
                <Plus />
                Assign access
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSheetKind("limit")}>
                <Plus />
                New limit
              </Button>
              <Button size="sm" onClick={() => setSheetKind("access")}>
                <Plus />
                New access
              </Button>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {scopedAssignments.length === 0 ? (
            <EmptyState
              title="No direct policies assigned"
              description="This scope currently relies on inherited organization, team, or project policies."
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {scopedAssignments.map((assignment) => {
                const policy =
                  assignment.policy_type === "access"
                    ? accessById.get(assignment.access_policy_id ?? "")
                    : limitById.get(assignment.limit_policy_id ?? "");
                return (
                  <div key={assignment.id} className="rounded-md border p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <span className="text-sm font-medium">
                          {policy?.name ?? "Unknown policy"}
                        </span>
                        <p className="text-xs capitalize text-muted-foreground">
                          {assignment.policy_type} policy
                        </p>
                      </div>
                      <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
                        {assignment.is_active ? "Active" : "Inactive"}
                      </StatusBadge>
                    </div>
                    {policy?.description ? (
                      <p className="mt-2 text-xs text-muted-foreground">{policy.description}</p>
                    ) : null}
                    {policy ? (
                      <div className="mt-3 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                        {assignment.policy_type === "access"
                          ? summarizeAccessPolicy(policy)
                          : summarizeLimitPolicy(policy)}
                      </div>
                    ) : null}
                    {canManage ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {policy ? (
                          <Button size="sm" variant="outline" asChild>
                            <Link
                              to={
                                assignment.policy_type === "access"
                                  ? `/policies/access/${policy.id}`
                                  : `/policies/limits/${policy.id}`
                              }
                            >
                              Edit policy
                            </Link>
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={deleteAssignment.isPending}
                          onClick={() => deleteAssignment.mutate({ assignmentId: assignment.id })}
                        >
                          Remove assignment
                        </Button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      <ScopedPolicySheet
        kind={sheetKind}
        target={target}
        onOpenChange={(open) => !open && setSheetKind(null)}
      />
      <AssignExistingPolicySheet
        kind={assignKind}
        target={target}
        accessPolicies={accessPolicies}
        limitPolicies={limitPolicies}
        assignedAccessPolicyIds={
          new Set(
            scopedAssignments
              .map((assignment) => assignment.access_policy_id)
              .filter((policyId): policyId is string => Boolean(policyId)),
          )
        }
        assignedLimitPolicyIds={
          new Set(
            scopedAssignments
              .map((assignment) => assignment.limit_policy_id)
              .filter((policyId): policyId is string => Boolean(policyId)),
          )
        }
        onOpenChange={(open) => !open && setAssignKind(null)}
      />
    </>
  );
}

function AssignExistingPolicySheet({
  kind,
  target,
  accessPolicies,
  limitPolicies,
  assignedAccessPolicyIds,
  assignedLimitPolicyIds,
  onOpenChange,
}: {
  kind: AssignKind;
  target: ScopeTarget;
  accessPolicies: AccessPolicyResponse[];
  limitPolicies: LimitPolicyResponse[];
  assignedAccessPolicyIds: Set<string>;
  assignedLimitPolicyIds: Set<string>;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [policyId, setPolicyId] = useState("");
  const createAssignment = useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost();
  const isAccess = kind === "access";
  const policies = isAccess
    ? accessPolicies.filter((policy) => !assignedAccessPolicyIds.has(policy.id))
    : limitPolicies.filter((policy) => !assignedLimitPolicyIds.has(policy.id));
  const assignTarget =
    target.type === "team"
      ? { scope_type: "team", team_id: target.teamId }
      : target.type === "project"
        ? { scope_type: "project", project_id: target.projectId }
        : { scope_type: "virtual_key", virtual_key_id: target.virtualKeyId };
  const submit = async () => {
    if (!kind || !policyId) return;
    try {
      await createAssignment.mutateAsync({
        data:
          kind === "access"
            ? { policy_type: "access", access_policy_id: policyId, ...assignTarget }
            : { policy_type: "limit", limit_policy_id: policyId, ...assignTarget },
      });
      toast.success("Policy assigned.");
      setPolicyId("");
      onOpenChange(false);
      await queryClient.invalidateQueries();
    } catch {
      toast.error("Policy could not be assigned.");
    }
  };

  return (
    <Sheet
      open={Boolean(kind)}
      onOpenChange={(open) => {
        if (!open) setPolicyId("");
        onOpenChange(open);
      }}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{isAccess ? "Assign access policy" : "Assign limit policy"}</SheetTitle>
          <SheetDescription>
            Assign an available policy directly to this {target.type}.
          </SheetDescription>
        </SheetHeader>
        <div className="grid gap-4 overflow-y-auto px-6 py-5">
          <Field label="Policy">
            <Select value={policyId} onValueChange={setPolicyId}>
              <SelectTrigger>
                <SelectValue placeholder="Select policy" />
              </SelectTrigger>
              <SelectContent>
                {policies.map((policy) => (
                  <SelectItem key={policy.id} value={policy.id}>
                    {policy.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {policies.length === 0 ? (
            <p className="text-sm text-muted-foreground">No available policies to assign.</p>
          ) : null}
        </div>
        <SheetFooter>
          <Button onClick={submit} disabled={!policyId || createAssignment.isPending}>
            Assign policy
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function ScopedPolicySheet({
  kind,
  target,
  onOpenChange,
}: {
  kind: SheetKind;
  target: ScopeTarget;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[] | null>(null);
  const [draftRoutes, setDraftRoutes] = useState<DraftAccessRoute[]>([]);
  const [draftRules, setDraftRules] = useState<DraftLimitRule[]>([]);
  const [ruleName, setRuleName] = useState("Rule");
  const [limitType, setLimitType] = useState("requests");
  const [limitValue, setLimitValue] = useState("");
  const [intervalUnit, setIntervalUnit] = useState("day");
  const [intervalCount, setIntervalCount] = useState("1");
  const isAccess = kind === "access";
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    accessOptionsParams(target),
    { query: { enabled: Boolean(isAccess) } },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? (accessOptionsQuery.data.data.providers ?? []) : [];
  const createScopedPolicy =
    useCreateScopedPolicyAssignmentApiV1PoliciesAssignmentsScopedPolicyPost();
  const reset = () => {
    setName("");
    setDescription("");
    setProviderId("");
    setPoolId("");
    setSelectedModels(null);
    setDraftRoutes([]);
    setDraftRules([]);
    setRuleName("Rule");
    setLimitType("requests");
    setLimitValue("");
    setIntervalUnit("day");
    setIntervalCount("1");
  };
  const assignTarget =
    target.type === "team"
      ? { scope_type: "team", team_id: target.teamId }
      : target.type === "project"
        ? { scope_type: "project", project_id: target.projectId }
        : { scope_type: "virtual_key", virtual_key_id: target.virtualKeyId };
  const currentLimitRule = (): DraftLimitRule => ({
    name: ruleName.trim() || "Rule",
    limitType,
    limitValue,
    intervalUnit,
    intervalCount,
  });
  const currentLimitRuleHasLimits = hasLimitRuleValues(currentLimitRule());
  const currentAccessRoute = (): DraftAccessRoute | null => {
    const provider = accessOptions.find((option) => option.id === providerId);
    const pool = pools.find((option) => option.id === poolId);
    if (!provider || !pool || effectiveSelectedModels.length === 0) return null;
    return {
      id: crypto.randomUUID(),
      providerId,
      providerLabel: provider.display_name,
      poolId,
      poolLabel: pool.name,
      modelIds: effectiveSelectedModels,
    };
  };
  const accessRoutesForSubmit = () => {
    const currentRoute = currentAccessRoute();
    return currentRoute ? [...draftRoutes, currentRoute] : draftRoutes;
  };
  const submit = async () => {
    if (!name.trim()) return;
    try {
      if (kind === "limit") {
        const rules = [...draftRules];
        if (currentLimitRuleHasLimits) {
          rules.push(currentLimitRule());
        }
        await createScopedPolicy.mutateAsync({
          data: {
            policy_type: "limit",
            limit_policy: {
              name,
              description: description || null,
              rules: rules.map(toLimitRuleInput),
            },
            ...assignTarget,
          },
        });
      }
      if (kind === "access") {
        const routes = accessRoutesForSubmit();
        if (routes.length === 0) return;
        await createScopedPolicy.mutateAsync({
          data: {
            policy_type: "access",
            access_policy: {
              name,
              description: description || null,
              routes: routes.map(toAccessRouteInput),
            },
            ...assignTarget,
          },
        });
      }
      toast.success("Policy created and assigned.");
      reset();
      onOpenChange(false);
      await queryClient.invalidateQueries();
    } catch {
      toast.error("Policy could not be created.");
    }
  };
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const providerModels = pools.find((pool) => pool.id === poolId)?.models ?? [];
  const effectiveSelectedModels = selectedModels ?? providerModels.map((model) => model.id);
  const canSubmit =
    Boolean(name.trim()) &&
    ((kind === "limit" && (draftRules.length > 0 || currentLimitRuleHasLimits)) ||
      (kind === "access" &&
        (draftRoutes.length > 0 ||
          Boolean(providerId && poolId && effectiveSelectedModels.length > 0))));
  const addDraftRule = () => {
    if (!currentLimitRuleHasLimits) return;
    setDraftRules((current) => [...current, currentLimitRule()]);
    setRuleName(`Rule ${draftRules.length + 2}`);
    setLimitValue("");
  };
  const addDraftRoute = () => {
    const route = currentAccessRoute();
    if (!route) return;
    setDraftRoutes((current) => [...current, route]);
    setProviderId("");
    setPoolId("");
    setSelectedModels(null);
  };

  return (
    <Sheet
      open={Boolean(kind)}
      onOpenChange={(open) => {
        if (!open) reset();
        onOpenChange(open);
      }}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{isAccess ? "New access policy" : "New limit policy"}</SheetTitle>
          <SheetDescription>
            This policy will be created and assigned directly to this {target.type}.
          </SheetDescription>
        </SheetHeader>
        <div className="grid gap-4 overflow-y-auto px-6 py-5">
          <Field label="Name">
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field label="Description">
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          {kind === "limit" ? (
            <>
              <div className="space-y-2 rounded-md border p-3">
                <div>
                  <div className="text-sm font-medium">Rules</div>
                  <p className="text-xs text-muted-foreground">
                    Add one rule at a time. Rules in the same policy are enforced together.
                  </p>
                </div>
                {draftRules.length > 0 ? (
                  <div className="space-y-2">
                    {draftRules.map((rule, index) => (
                      <div
                        key={`${rule.name}-${index}`}
                        className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-xs"
                      >
                        <span className="min-w-0 truncate">{formatDraftLimitRule(rule)}</span>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          aria-label="Remove rule"
                          onClick={() =>
                            setDraftRules((current) =>
                              current.filter((_, ruleIndex) => ruleIndex !== index),
                            )
                          }
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <Field label="Rule name">
                <Input value={ruleName} onChange={(event) => setRuleName(event.target.value)} />
              </Field>
              <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
                <Field label="Every">
                  <Input
                    type="number"
                    min={1}
                    value={intervalCount}
                    disabled={intervalUnit === "lifetime"}
                    onChange={(event) => setIntervalCount(event.target.value)}
                  />
                </Field>
                <Field label="Interval">
                  <Select value={intervalUnit} onValueChange={setIntervalUnit}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="minute">Minute</SelectItem>
                      <SelectItem value="hour">Hour</SelectItem>
                      <SelectItem value="day">Day</SelectItem>
                      <SelectItem value="week">Week</SelectItem>
                      <SelectItem value="month">Month</SelectItem>
                      <SelectItem value="lifetime">Lifetime</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field label="Limit type">
                <Select value={limitType} onValueChange={setLimitType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {limitTypeOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={limitType === "budget_cents" ? "Amount ($)" : "Value"}>
                <Input
                  type="number"
                  min={1}
                  value={limitValue}
                  onChange={(event) => setLimitValue(event.target.value)}
                />
              </Field>
              <Button
                type="button"
                variant="outline"
                onClick={addDraftRule}
                disabled={!currentLimitRuleHasLimits}
              >
                <Plus />
                Add rule
              </Button>
            </>
          ) : null}
          {kind === "access" ? (
            <div className="grid gap-3 rounded-md border p-3">
              {draftRoutes.length > 0 ? (
                <div className="grid gap-2">
                  {draftRoutes.map((route) => (
                    <div
                      key={route.id}
                      className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-xs"
                    >
                      <span className="min-w-0 truncate">
                        {route.providerLabel} / {route.poolLabel} · {route.modelIds.length} model
                        {route.modelIds.length === 1 ? "" : "s"}
                      </span>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        aria-label="Remove route"
                        onClick={() =>
                          setDraftRoutes((current) =>
                            current.filter((candidate) => candidate.id !== route.id),
                          )
                        }
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  ))}
                </div>
              ) : null}
              <AccessRouteFields
                providers={accessOptions}
                providerId={providerId}
                poolId={poolId}
                selectedModels={effectiveSelectedModels}
                onProviderChange={(value) => {
                  const nextProvider = accessOptions.find((provider) => provider.id === value);
                  const nextPool = nextProvider?.pools?.[0];
                  setProviderId(value);
                  setPoolId(nextPool?.id ?? "");
                  setSelectedModels(nextPool?.models?.map((model) => model.id) ?? []);
                }}
                onPoolChange={(value) => {
                  const nextPool = pools.find((pool) => pool.id === value);
                  setPoolId(value);
                  setSelectedModels(nextPool?.models?.map((model) => model.id) ?? []);
                }}
                onModelsChange={setSelectedModels}
              />
              <Button
                type="button"
                variant="outline"
                onClick={addDraftRoute}
                disabled={!providerId || !poolId || effectiveSelectedModels.length === 0}
              >
                <Plus />
                Add route
              </Button>
            </div>
          ) : null}
        </div>
        <SheetFooter>
          <Button onClick={submit} disabled={!canSubmit || createScopedPolicy.isPending}>
            Create and assign
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function hasLimitRuleValues(rule: DraftLimitRule) {
  return Boolean(rule.limitValue.trim());
}

function toLimitRuleInput(rule: DraftLimitRule): LimitPolicyRuleInput {
  return {
    name: rule.name,
    limit_type: rule.limitType,
    limit_value:
      rule.limitType === "budget_cents"
        ? Math.round(Number(rule.limitValue) * 100)
        : Number(rule.limitValue),
    interval_unit: rule.intervalUnit,
    interval_count: rule.intervalUnit === "lifetime" ? 1 : Number(rule.intervalCount || 1),
    is_active: true,
  };
}

function toAccessRouteInput(route: DraftAccessRoute): AccessPolicyRouteInput {
  return {
    provider_id: route.providerId,
    credential_pool_id: route.poolId,
    model_offering_ids: route.modelIds,
  };
}

function formatDraftLimitRule(rule: DraftLimitRule) {
  const typeLabel =
    limitTypeOptions.find((option) => option.value === rule.limitType)?.label ?? rule.limitType;
  const value =
    rule.limitType === "budget_cents"
      ? `$${Number(rule.limitValue).toLocaleString()}`
      : Number(rule.limitValue).toLocaleString();
  return `${rule.name}: ${typeLabel} ${value} ${formatInterval(rule.intervalUnit, rule.intervalCount)}`;
}

function formatInterval(intervalUnit: string, intervalCount: string | number) {
  if (intervalUnit === "lifetime") return "over lifetime";
  const count = Number(intervalCount) || 1;
  return `every ${count} ${intervalUnit}${count === 1 ? "" : "s"}`;
}

function summarizeAccessPolicy(policy: AccessPolicyResponse | LimitPolicyResponse) {
  if (!("routes" in policy)) return "";
  const routeCount = policy.routes?.length ?? 0;
  const modelCount = (policy.routes ?? []).reduce(
    (total, route) => total + route.model_offering_ids.length,
    0,
  );
  return `${routeCount} route${routeCount === 1 ? "" : "s"} · ${modelCount} model${modelCount === 1 ? "" : "s"}`;
}

function summarizeLimitPolicy(policy: AccessPolicyResponse | LimitPolicyResponse) {
  if (!("rules" in policy)) return "";
  const rules = policy.rules ?? [];
  if (rules.length === 0) return "No rules configured";
  return rules
    .map((rule) => {
      const typeLabel =
        limitTypeOptions.find((option) => option.value === rule.limit_type)?.label ??
        rule.limit_type;
      const value =
        rule.limit_type === "budget_cents"
          ? `$${(rule.limit_value / 100).toLocaleString()}`
          : rule.limit_value.toLocaleString();
      return `${typeLabel}: ${value} ${formatInterval(rule.interval_unit, rule.interval_count)}`;
    })
    .join(" · ");
}

function AccessRouteFields({
  providers,
  providerId,
  poolId,
  selectedModels,
  onProviderChange,
  onPoolChange,
  onModelsChange,
}: {
  providers: AccessPolicyProviderOption[];
  providerId: string;
  poolId: string;
  selectedModels: string[];
  onProviderChange: (providerId: string) => void;
  onPoolChange: (poolId: string) => void;
  onModelsChange: (models: string[]) => void;
}) {
  const pools = providers.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
  return (
    <>
      <Field label="Provider">
        <Select value={providerId} onValueChange={onProviderChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select provider" />
          </SelectTrigger>
          <SelectContent>
            {providers.map((provider) => (
              <SelectItem key={provider.id} value={provider.id}>
                {provider.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Credential pool">
        <Select value={poolId} onValueChange={onPoolChange} disabled={!providerId}>
          <SelectTrigger>
            <SelectValue placeholder="Select pool" />
          </SelectTrigger>
          <SelectContent>
            {pools.map((pool) => (
              <SelectItem key={pool.id} value={pool.id}>
                {pool.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <ModelChecklist
        models={models.map((model) => ({
          id: model.id,
          label: model.provider_model_name,
          sublabel: model.alias,
        }))}
        selected={selectedModels}
        onChange={onModelsChange}
      />
    </>
  );
}

function ModelChecklist({
  models,
  selected,
  onChange,
}: {
  models: { id: string; label: string; sublabel?: string | null }[];
  selected: string[];
  onChange: (models: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = models.filter((model) => {
    const term = search.trim().toLowerCase();
    return (
      !term ||
      [model.label, model.sublabel]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(term))
    );
  });
  const visibleIds = filtered.map((model) => model.id);
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <Label>Models</Label>
        <div className="flex gap-1">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onChange(Array.from(new Set([...selected, ...visibleIds])))}
          >
            Select visible
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onChange(selected.filter((id) => !visibleIds.includes(id)))}
          >
            Clear visible
          </Button>
        </div>
      </div>
      <Input
        placeholder="Search models"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div className="max-h-72 overflow-y-auto rounded-md border">
        {filtered.length === 0 ? (
          <p className="p-3 text-sm text-muted-foreground">No models available.</p>
        ) : (
          filtered.map((model) => (
            <label
              key={model.id}
              className="flex cursor-pointer items-start gap-2 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-muted/50"
            >
              <Checkbox
                checked={selected.includes(model.id)}
                onCheckedChange={(checked) =>
                  onChange(
                    checked
                      ? Array.from(new Set([...selected, model.id]))
                      : selected.filter((id) => id !== model.id),
                  )
                }
              />
              <span>
                <span className="block font-medium">{model.label}</span>
                {model.sublabel ? (
                  <span className="block text-xs text-muted-foreground">{model.sublabel}</span>
                ) : null}
              </span>
            </label>
          ))
        )}
      </div>
      <p className="text-xs text-muted-foreground">{selected.length} models selected.</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function accessOptionsParams(target: ScopeTarget) {
  if (target.type === "team") {
    return { scope_type: "team", team_id: target.teamId };
  }
  if (target.type === "project") {
    return { scope_type: "project", project_id: target.projectId };
  }
  return {
    scope_type: "virtual_key",
    project_id: target.projectId,
    virtual_key_id: target.virtualKeyId,
  };
}
