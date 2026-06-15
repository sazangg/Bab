import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Pencil,
  GitBranch,
  Plus,
  Route,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  getAccessPolicyImpactApiV1PoliciesAccessPolicyIdImpactGet,
  getAccessPolicyRouteImpactApiV1PoliciesAccessRoutesRouteIdImpactGet,
  getLimitPolicyImpactApiV1PoliciesLimitsPolicyIdImpactGet,
  getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet,
  useCreateAccessPolicyApiV1PoliciesAccessPost,
  useCreateAccessPolicyRouteApiV1PoliciesAccessPolicyIdRoutesPost,
  useCreateLimitPolicyApiV1PoliciesLimitsPost,
  useCreateLimitPolicyRuleApiV1PoliciesLimitsPolicyIdRulesPost,
  useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost,
  useDeleteAccessPolicyApiV1PoliciesAccessPolicyIdDelete,
  useDeleteAccessPolicyRouteApiV1PoliciesAccessRoutesRouteIdDelete,
  useDeleteLimitPolicyApiV1PoliciesLimitsPolicyIdDelete,
  useDeleteLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdDelete,
  useDeletePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdDelete,
  useGetAccessPolicyApiV1PoliciesAccessPolicyIdGet,
  useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet,
  useGetLimitPolicyApiV1PoliciesLimitsPolicyIdGet,
  useListAccessPoliciesApiV1PoliciesAccessGet,
  useListLimitPoliciesApiV1PoliciesLimitsGet,
  useListPolicyAssignmentsApiV1PoliciesAssignmentsGet,
  useUpdateAccessPolicyApiV1PoliciesAccessPolicyIdPatch,
  useUpdateAccessPolicyRouteApiV1PoliciesAccessRoutesRouteIdPatch,
  useUpdateLimitPolicyApiV1PoliciesLimitsPolicyIdPatch,
  useUpdateLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdPatch,
  useUpdatePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdPatch,
} from "@/shared/api/generated/policies/policies";
import { ConfirmationDialog } from "@/features/policies/components/ConfirmationDialog";
import {
  LimitRuleFilterFields,
  LimitRuleFiltersSummary,
  type LimitRuleFilterValue,
} from "@/features/policies/components/LimitRuleFilterFields";
import {
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";
import type {
  AccessPolicyResponse,
  AccessPolicyProviderOption,
  AccessPolicyRouteInput,
  AccessPolicyRouteResponse,
  LimitPolicyResponse,
  LimitPolicyRuleResponse,
  PolicyAssignmentResponse,
  PolicyImpactResponse,
  ProjectResponse,
  TeamResponse,
} from "@/shared/api/generated/schemas";
import {
  useListProjectsApiV1ProjectsGet,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
} from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { EmptyState } from "@/shared/components/EmptyState";
import { ImpactConfirmationDialog } from "@/shared/components/ImpactConfirmationDialog";
import { ModelMultiselect } from "@/shared/components/ModelMultiselect";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatCard } from "@/shared/components/StatCard";
import { StatusBadge } from "@/shared/components/StatusBadge";

type SheetKind = "access" | "limit" | null;
type RouteSheetState = { policy: AccessPolicyResponse } | null;
type LimitRulesSheetState = { policy: LimitPolicyResponse } | null;
type PolicySettingsSheetState =
  | { kind: "access"; policy: AccessPolicyResponse }
  | { kind: "limit"; policy: LimitPolicyResponse }
  | null;
type AssignmentSheetState =
  | { policyType: "access"; policyId: string }
  | { policyType: "limit"; policyId: string }
  | null;
type DraftLimitRule = {
  id: string;
  name: string;
  limitType: string;
  limitValue: string;
  intervalUnit: string;
  intervalCount: string;
  filters: LimitRuleFilterValue;
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

const emptyLimitRuleFilters = (): LimitRuleFilterValue => ({
  providerId: "",
  poolId: "",
  modelId: "",
  accessPolicyId: "",
});

function limitRuleFiltersPayload(filters: LimitRuleFilterValue) {
  return {
    provider_id: filters.providerId || null,
    credential_pool_id: filters.poolId || null,
    model_offering_id: filters.modelId || null,
    access_policy_id: filters.accessPolicyId || null,
  };
}

function accessPolicyStatus(policy: AccessPolicyResponse, assignments: number) {
  if (!policy.is_active) return { label: "Inactive", variant: "inactive" as const };
  if (assignments === 0) return { label: "Unassigned", variant: "muted" as const };
  if ((policy.routes ?? []).length === 0) {
    return { label: "No routable routes", variant: "expired" as const };
  }
  return { label: "Active", variant: "active" as const };
}

function limitPolicyStatus(policy: LimitPolicyResponse, assignments: number) {
  if (!policy.is_active) return { label: "Inactive", variant: "inactive" as const };
  if (assignments === 0) return { label: "Unassigned", variant: "muted" as const };
  if ((policy.rules ?? []).filter((rule) => rule.is_active).length === 0) {
    return { label: "No active rules", variant: "expired" as const };
  }
  return { label: "Blocking traffic", variant: "active" as const };
}

type ImpactConfirmationState = {
  title: string;
  impact: PolicyImpactResponse;
  onConfirm: () => void;
} | null;

function useImpactConfirmation() {
  const [state, setState] = useState<ImpactConfirmationState>(null);
  const [isLoadingImpact, setIsLoadingImpact] = useState(false);
  const requestImpactConfirmation = async (
    title: string,
    fetchImpact: () => Promise<{ status: number; data: unknown }>,
    onConfirm: () => void,
  ) => {
    setIsLoadingImpact(true);
    try {
      const response = await fetchImpact();
      if (response.status !== 200) {
        toast.error("Impact preview could not be loaded.");
        return;
      }
      setState({ title, impact: response.data as PolicyImpactResponse, onConfirm });
    } finally {
      setIsLoadingImpact(false);
    }
  };
  const dialog = (
    <ImpactConfirmationDialog
      open={Boolean(state)}
      title={state?.title ?? ""}
      description="Review the affected scopes before removing this policy item."
      confirmLabel="Delete"
      onOpenChange={(open) => !open && setState(null)}
      onConfirm={() => {
        state?.onConfirm();
        setState(null);
      }}
    >
      {state ? <PolicyImpactPreview impact={state.impact} /> : null}
    </ImpactConfirmationDialog>
  );
  return { requestImpactConfirmation, isLoadingImpact, dialog };
}

function PolicyImpactPreview({ impact }: { impact: PolicyImpactResponse }) {
  const unusableKeys = impact.virtual_keys_would_become_unusable ?? [];
  return (
    <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm">
      <div className="grid grid-cols-3 gap-2">
        <ImpactCount label="Teams" value={impact.affected_team_count ?? 0} />
        <ImpactCount label="Projects" value={impact.affected_project_count ?? 0} />
        <ImpactCount label="Keys" value={impact.affected_virtual_key_count ?? 0} />
      </div>
      {(impact.virtual_keys_would_become_unusable_count ?? 0) > 0 ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
          <div className="font-medium">
            {impact.virtual_keys_would_become_unusable_count} virtual key
            {impact.virtual_keys_would_become_unusable_count === 1 ? "" : "s"} would become
            unroutable
          </div>
          <div className="mt-1 text-xs">
            {unusableKeys
              .slice(0, 5)
              .map((key) => key.name)
              .join(", ")}
            {unusableKeys.length > 5 ? `, +${unusableKeys.length - 5} more` : ""}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ImpactCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

type ActionConfirmationState = {
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
} | null;

function useActionConfirmation() {
  const [state, setState] = useState<ActionConfirmationState>(null);
  const requestActionConfirmation = (nextState: NonNullable<ActionConfirmationState>) =>
    setState(nextState);
  const dialog = (
    <ConfirmationDialog
      open={Boolean(state)}
      title={state?.title ?? ""}
      description={state?.description}
      confirmLabel={state?.confirmLabel}
      onOpenChange={(open) => !open && setState(null)}
      onConfirm={() => {
        state?.onConfirm();
        setState(null);
      }}
    />
  );
  return { requestActionConfirmation, dialog };
}

function canManagePolicyDefinition(
  user: Parameters<typeof hasPermission>[0],
  policy: AccessPolicyResponse | LimitPolicyResponse,
) {
  if (hasPermission(user, "policies.manage")) return true;
  if (!policy.owning_scope_type) return false;
  return hasAnyTeamAdminMembership(user) || hasAnyProjectAdminMembership(user);
}

function formatAssignmentTarget(
  assignment: PolicyAssignmentResponse,
  teamNames: Map<string, string>,
  projectNames: Map<string, string>,
) {
  if (assignment.scope_type === "org") return "Organization";
  if (assignment.scope_type === "team" && assignment.team_id) {
    return teamNames.get(assignment.team_id) ?? assignment.team_id;
  }
  if (assignment.scope_type === "project" && assignment.project_id) {
    return projectNames.get(assignment.project_id) ?? assignment.project_id;
  }
  return assignment.virtual_key_id ?? "Unknown target";
}

export function PoliciesPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sheetKind, setSheetKind] = useState<SheetKind>(null);
  const [routeSheet, setRouteSheet] = useState<RouteSheetState>(null);
  const [limitRulesSheet, setLimitRulesSheet] = useState<LimitRulesSheetState>(null);
  const [policySettingsSheet, setPolicySettingsSheet] = useState<PolicySettingsSheetState>(null);
  const [assignmentSheet, setAssignmentSheet] = useState<AssignmentSheetState>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const activeTab = searchParams.get("tab") === "limits" ? "limits" : "access";
  const accessQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const limitsQuery = useListLimitPoliciesApiV1PoliciesLimitsGet();
  const assignmentsQuery = useListPolicyAssignmentsApiV1PoliciesAssignmentsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManagePolicies = hasPermission(currentUser, "policies.manage");
  const canAssignPolicies =
    canManagePolicies ||
    hasAnyTeamAdminMembership(currentUser) ||
    hasAnyProjectAdminMembership(currentUser);
  const canManageDefinition = (policy: AccessPolicyResponse | LimitPolicyResponse) =>
    canManagePolicyDefinition(currentUser, policy);
  const accessPolicies = accessQuery.data?.status === 200 ? accessQuery.data.data : [];
  const limitPolicies = limitsQuery.data?.status === 200 ? limitsQuery.data.data : [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const assignmentCount = (policyId: string, type: "access" | "limit") =>
    assignments.filter((assignment) =>
      type === "access"
        ? assignment.access_policy_id === policyId
        : assignment.limit_policy_id === policyId,
    ).length;
  const invalidatePolicies = async () => {
    await queryClient.invalidateQueries();
  };
  const matchesFilters = (policy: AccessPolicyResponse | LimitPolicyResponse) => {
    const term = search.trim().toLowerCase();
    const matchesSearch =
      !term ||
      [policy.name, policy.description]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(term));
    const matchesStatus =
      status === "all" ||
      (status === "active" && policy.is_active) ||
      (status === "inactive" && !policy.is_active);
    return matchesSearch && matchesStatus;
  };
  const filteredAccessPolicies = accessPolicies.filter(matchesFilters);
  const filteredLimitPolicies = limitPolicies.filter(matchesFilters);
  const currentTabIsLimit = activeTab === "limits";
  const activeRouteSheet = routeSheet
    ? {
        policy:
          accessPolicies.find((policy) => policy.id === routeSheet.policy.id) ?? routeSheet.policy,
      }
    : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Policies"
        description="Access policies define where traffic can route. Limit policies define budgets and caps that compose across org, team, project, and key scopes."
        actions={
          <div className="flex items-center gap-2">
            {canManagePolicies ? (
              <Button onClick={() => setSheetKind(currentTabIsLimit ? "limit" : "access")}>
                <Plus />
                {currentTabIsLimit ? "New limit policy" : "New access policy"}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="flex flex-col gap-4">
        <Tabs
          value={activeTab}
          onValueChange={(value) => setSearchParams({ tab: value })}
          className="gap-4"
        >
          <TabsList>
            <TabsTrigger value="access">
              <GitBranch />
              Access policies
            </TabsTrigger>
            <TabsTrigger value="limits">
              <ShieldCheck />
              Limit policies
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="flex flex-col gap-3 rounded-md border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={`Search ${currentTabIsLimit ? "limit" : "access"} policies`}
              className="pl-9"
            />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-full sm:w-44">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <PolicyCard
          title={currentTabIsLimit ? "Limit policies" : "Access policies"}
          description={
            currentTabIsLimit
              ? "Reusable budgets, request caps, and token caps."
              : "Reusable provider, pool, and model route sets."
          }
          icon={currentTabIsLimit ? ShieldCheck : GitBranch}
        >
          {currentTabIsLimit ? (
            <LimitPoliciesTable
              policies={filteredLimitPolicies}
              assignmentCount={assignmentCount}
              isLoading={limitsQuery.isPending}
              onConfigureRules={(policy) => setLimitRulesSheet({ policy })}
              onEditPolicy={(policy) => setPolicySettingsSheet({ kind: "limit", policy })}
              onAssign={(policy) =>
                setAssignmentSheet({ policyType: "limit", policyId: policy.id })
              }
              canManageDefinition={canManageDefinition}
              canAssign={canAssignPolicies}
            />
          ) : (
            <AccessPoliciesTable
              policies={filteredAccessPolicies}
              assignmentCount={assignmentCount}
              isLoading={accessQuery.isPending}
              onConfigureRoutes={(policy) => setRouteSheet({ policy })}
              onEditPolicy={(policy) => setPolicySettingsSheet({ kind: "access", policy })}
              onAssign={(policy) =>
                setAssignmentSheet({ policyType: "access", policyId: policy.id })
              }
              canManageDefinition={canManageDefinition}
              canAssign={canAssignPolicies}
            />
          )}
        </PolicyCard>
      </div>

      <CreatePolicySheet
        kind={sheetKind}
        onOpenChange={(open) => !open && setSheetKind(null)}
        onCreated={async () => {
          setSheetKind(null);
          await invalidatePolicies();
        }}
      />
      <RouteSheet
        state={activeRouteSheet}
        onOpenChange={(open) => !open && setRouteSheet(null)}
        onChanged={invalidatePolicies}
      />
      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
        onChanged={invalidatePolicies}
      />
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
      />
      <AssignmentSheet
        state={assignmentSheet}
        onOpenChange={(open) => !open && setAssignmentSheet(null)}
        onChanged={invalidatePolicies}
        canAssignOrg={canManagePolicies}
      />
    </div>
  );
}

export function AccessPolicyDetailPage() {
  const { policyId = "" } = useParams();
  const queryClient = useQueryClient();
  const [routeSheet, setRouteSheet] = useState<RouteSheetState>(null);
  const [policySettingsSheet, setPolicySettingsSheet] = useState<PolicySettingsSheetState>(null);
  const [assignmentSheet, setAssignmentSheet] = useState<AssignmentSheetState>(null);
  const policyQuery = useGetAccessPolicyApiV1PoliciesAccessPolicyIdGet(policyId, {
    query: { enabled: Boolean(policyId) },
  });
  const assignmentsQuery = useListPolicyAssignmentsApiV1PoliciesAssignmentsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManagePolicies = hasPermission(currentUser, "policies.manage");
  const canAssignPolicies =
    canManagePolicies ||
    hasAnyTeamAdminMembership(currentUser) ||
    hasAnyProjectAdminMembership(currentUser);
  const policy = policyQuery.data?.status === 200 ? policyQuery.data.data : null;
  const assignments =
    assignmentsQuery.data?.status === 200
      ? assignmentsQuery.data.data.filter((assignment) => assignment.access_policy_id === policyId)
      : [];
  const invalidatePolicies = async () => {
    await queryClient.invalidateQueries();
  };

  if (policyQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading access policy...</p>;
  }
  if (!policy) {
    return (
      <EmptyState title="Access policy not found" description="The policy may have been removed." />
    );
  }

  const routeCount = policy.routes?.length ?? 0;
  const modelCount = countRouteModels(policy);
  const canManageDefinition = canManagePolicyDefinition(currentUser, policy);
  const activeRouteSheet = routeSheet ? { policy } : null;

  return (
    <>
      <PolicyDetailLayout
        title={policy.name}
        description={policy.description || "Access policy route configuration."}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" asChild>
              <Link to="/policies">
                <ArrowLeft />
                Policies
              </Link>
            </Button>
            {canAssignPolicies ? (
              <Button
                variant="outline"
                onClick={() => setAssignmentSheet({ policyType: "access", policyId })}
              >
                <Plus />
                Assign
              </Button>
            ) : null}
            {canManageDefinition ? (
              <Button
                variant="outline"
                onClick={() => setPolicySettingsSheet({ kind: "access", policy })}
              >
                <Pencil />
                Edit policy
              </Button>
            ) : null}
            {canManageDefinition ? (
              <Button onClick={() => setRouteSheet({ policy })}>
                <Route />
                Configure routes
              </Button>
            ) : null}
          </div>
        }
        metrics={[
          { label: "Routes", value: routeCount },
          { label: "Models", value: modelCount },
          { label: "Assignments", value: assignments.length },
          { label: "Status", value: policy.is_active ? "Active" : "Inactive" },
        ]}
        detailTitle="Access routes"
        detailDescription="Routes decide which provider pool can serve selected models."
        detailIcon={Route}
        detailContent={<AccessRoutesDetailTable routes={policy.routes ?? []} />}
        assignments={assignments}
        onChanged={invalidatePolicies}
        canManageAssignments={canAssignPolicies}
      />
      <RouteSheet
        state={activeRouteSheet}
        onOpenChange={(open) => !open && setRouteSheet(null)}
        onChanged={invalidatePolicies}
      />
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
      />
      <AssignmentSheet
        state={assignmentSheet}
        onOpenChange={(open) => !open && setAssignmentSheet(null)}
        onChanged={invalidatePolicies}
        canAssignOrg={canManagePolicies}
      />
    </>
  );
}

export function LimitPolicyDetailPage() {
  const { policyId = "" } = useParams();
  const queryClient = useQueryClient();
  const [limitRulesSheet, setLimitRulesSheet] = useState<LimitRulesSheetState>(null);
  const [policySettingsSheet, setPolicySettingsSheet] = useState<PolicySettingsSheetState>(null);
  const [assignmentSheet, setAssignmentSheet] = useState<AssignmentSheetState>(null);
  const policyQuery = useGetLimitPolicyApiV1PoliciesLimitsPolicyIdGet(policyId, {
    query: { enabled: Boolean(policyId) },
  });
  const assignmentsQuery = useListPolicyAssignmentsApiV1PoliciesAssignmentsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManagePolicies = hasPermission(currentUser, "policies.manage");
  const canAssignPolicies =
    canManagePolicies ||
    hasAnyTeamAdminMembership(currentUser) ||
    hasAnyProjectAdminMembership(currentUser);
  const policy = policyQuery.data?.status === 200 ? policyQuery.data.data : null;
  const assignments =
    assignmentsQuery.data?.status === 200
      ? assignmentsQuery.data.data.filter((assignment) => assignment.limit_policy_id === policyId)
      : [];
  const invalidatePolicies = async () => {
    await queryClient.invalidateQueries();
  };

  if (policyQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading limit policy...</p>;
  }
  if (!policy) {
    return (
      <EmptyState title="Limit policy not found" description="The policy may have been removed." />
    );
  }

  const rules = policy.rules ?? [];
  const canManageDefinition = canManagePolicyDefinition(currentUser, policy);

  return (
    <>
      <PolicyDetailLayout
        title={policy.name}
        description={policy.description || "Limit policy rule configuration."}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" asChild>
              <Link to="/policies?tab=limits">
                <ArrowLeft />
                Policies
              </Link>
            </Button>
            {canAssignPolicies ? (
              <Button
                variant="outline"
                onClick={() => setAssignmentSheet({ policyType: "limit", policyId })}
              >
                <Plus />
                Assign
              </Button>
            ) : null}
            {canManageDefinition ? (
              <Button
                variant="outline"
                onClick={() => setPolicySettingsSheet({ kind: "limit", policy })}
              >
                <Pencil />
                Edit policy
              </Button>
            ) : null}
            {canManageDefinition ? (
              <Button onClick={() => setLimitRulesSheet({ policy })}>
                <SlidersHorizontal />
                Manage rules
              </Button>
            ) : null}
          </div>
        }
        metrics={[
          { label: "Rules", value: rules.length },
          { label: "Assignments", value: assignments.length },
          { label: "Active rules", value: rules.filter((rule) => rule.is_active).length },
          { label: "Status", value: policy.is_active ? "Active" : "Inactive" },
        ]}
        detailTitle="Limit rules"
        detailDescription="Rules compose across matching scopes and dimensions."
        detailIcon={SlidersHorizontal}
        detailContent={<LimitRulesDetailTable rules={rules} />}
        assignments={assignments}
        onChanged={invalidatePolicies}
        canManageAssignments={canAssignPolicies}
      />
      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
        onChanged={invalidatePolicies}
      />
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
      />
      <AssignmentSheet
        state={assignmentSheet}
        onOpenChange={(open) => !open && setAssignmentSheet(null)}
        onChanged={invalidatePolicies}
        canAssignOrg={canManagePolicies}
      />
    </>
  );
}

function PolicyCard({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description: string;
  icon: typeof GitBranch;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="rounded-md border bg-muted p-2">
            <Icon className="size-4" />
          </div>
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function PolicyDetailLayout({
  title,
  description,
  actions,
  metrics,
  detailTitle,
  detailDescription,
  detailIcon,
  detailContent,
  assignments,
  onChanged,
  canManageAssignments,
}: {
  title: string;
  description: string;
  actions: ReactNode;
  metrics: { label: string; value: ReactNode }[];
  detailTitle: string;
  detailDescription: string;
  detailIcon: typeof GitBranch;
  detailContent: ReactNode;
  assignments: PolicyAssignmentResponse[];
  onChanged: () => Promise<void>;
  canManageAssignments: boolean;
}) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={title} description={description} actions={actions} />
      <div className="grid gap-3 md:grid-cols-4">
        {metrics.map((metric) => (
          <StatCard key={metric.label} label={metric.label} value={metric.value} />
        ))}
      </div>
      <PolicyCard title={detailTitle} description={detailDescription} icon={detailIcon}>
        {detailContent}
      </PolicyCard>
      <PolicyAssignmentsSection
        assignments={assignments}
        onChanged={onChanged}
        canManageAssignments={canManageAssignments}
      />
    </div>
  );
}

function AccessRoutesDetailTable({ routes }: { routes: AccessPolicyRouteResponse[] }) {
  const columns: DataTableColumn<AccessPolicyRouteResponse>[] = [
    { key: "route", header: "Route", cell: (route) => <RouteProviderPool route={route} /> },
    {
      key: "models",
      header: "Model offerings",
      cell: (route) => <RouteModelNames route={route} />,
    },
    {
      key: "routing",
      header: "Routing",
      className: "text-sm",
      cell: (route) => (
        <>
          Priority {route.priority}
          <div className="text-xs text-muted-foreground">Tie-break weight {route.weight}</div>
        </>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (route) => (
        <StatusBadge variant={route.is_active ? "active" : "inactive"}>
          {route.is_active ? "Active" : "Inactive"}
        </StatusBadge>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={routes}
      getRowKey={(route) => route.id}
      empty={{
        title: "No routes configured",
        description:
          "Add at least one provider pool and model route before assigning this policy.",
      }}
    />
  );
}

function RouteProviderPool({ route }: { route: AccessPolicyRouteResponse }) {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(route.provider_id, {
    query: { enabled: Boolean(route.provider_id) },
  });
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const provider = providers.find((item) => item.id === route.provider_id);
  const pool = pools.find((item) => item.id === route.credential_pool_id);
  return (
    <div>
      <div className="font-medium">{provider?.display_name ?? route.provider_id.slice(0, 8)}</div>
      <div className="text-xs text-muted-foreground">
        {pool?.name ?? route.credential_pool_id.slice(0, 8)}
      </div>
    </div>
  );
}

function RouteModelNames({ route }: { route: AccessPolicyRouteResponse }) {
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(
    route.provider_id,
    { limit: 1000 },
    { query: { enabled: Boolean(route.provider_id) } },
  );
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data.items : [];
  const labels = route.model_offering_ids
    .map((id) => models.find((model) => model.id === id)?.provider_model_name ?? id.slice(0, 8))
    .sort((left, right) => left.localeCompare(right));
  if (labels.length === 0) return <span className="text-sm text-muted-foreground">No models</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {labels.slice(0, 8).map((label) => (
        <span key={label} className="rounded-md border bg-muted px-2 py-1 text-xs">
          {label}
        </span>
      ))}
      {labels.length > 8 ? (
        <span className="rounded-md border bg-muted px-2 py-1 text-xs">
          +{labels.length - 8} more
        </span>
      ) : null}
    </div>
  );
}

function LimitRulesDetailTable({ rules }: { rules: LimitPolicyRuleResponse[] }) {
  const columns: DataTableColumn<LimitPolicyRuleResponse>[] = [
    { key: "rule", header: "Rule", className: "font-medium", cell: (rule) => rule.name },
    {
      key: "interval",
      header: "Interval",
      cell: (rule) => formatInterval(rule.interval_unit, rule.interval_count),
    },
    {
      key: "limit",
      header: "Limit",
      className: "text-sm text-muted-foreground",
      cell: (rule) => formatRuleSummary(rule),
    },
    {
      key: "filters",
      header: "Filters",
      className: "text-xs text-muted-foreground",
      cell: (rule) => <LimitRuleFiltersSummary rule={rule} />,
    },
    {
      key: "status",
      header: "Status",
      cell: (rule) => (
        <StatusBadge variant={rule.is_active ? "active" : "inactive"}>
          {rule.is_active ? "Active" : "Inactive"}
        </StatusBadge>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={rules}
      getRowKey={(rule) => rule.id}
      empty={{
        title: "No rules configured",
        description: "Add budget, request, or token rules before assigning this policy.",
      }}
    />
  );
}

function PolicyAssignmentsSection({
  assignments,
  onChanged,
  canManageAssignments,
}: {
  assignments: PolicyAssignmentResponse[];
  onChanged: () => Promise<void>;
  canManageAssignments: boolean;
}) {
  const [scopeFilter, setScopeFilter] = useState("all");
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamNames = new Map(teams.map((team) => [team.id, team.name]));
  const projectNames = new Map(projects.map((project) => [project.id, project.name]));
  const { requestActionConfirmation, dialog: actionConfirmationDialog } = useActionConfirmation();
  const updateAssignment = useUpdatePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Assignment updated.");
        await onChanged();
      },
      onError: () => toast.error("Assignment could not be updated."),
    },
  });
  const deleteAssignment = useDeletePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Assignment removed.");
        await onChanged();
      },
      onError: () => toast.error("Assignment could not be removed."),
    },
  });
  const filteredAssignments =
    scopeFilter === "all"
      ? assignments
      : assignments.filter((assignment) => assignment.scope_type === scopeFilter);
  const handleDeleteAssignment = (assignment: PolicyAssignmentResponse) => {
    requestActionConfirmation({
      title: "Remove policy assignment?",
      description:
        "This removes the policy from the selected scope. Inherited policies from higher scopes may still apply.",
      confirmLabel: "Remove",
      onConfirm: () => deleteAssignment.mutate({ assignmentId: assignment.id }),
    });
  };
  const columns: DataTableColumn<PolicyAssignmentResponse>[] = [
    {
      key: "scope",
      header: "Scope",
      cell: (assignment) => (
        <>
          <div className="capitalize">{assignment.scope_type.replace("_", " ")}</div>
          <div className="text-xs text-muted-foreground">
            {formatAssignmentTarget(assignment, teamNames, projectNames)}
          </div>
        </>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (assignment) =>
        canManageAssignments ? (
          <div className="flex items-center gap-2">
            <Switch
              checked={assignment.is_active}
              disabled={updateAssignment.isPending}
              onCheckedChange={(checked) =>
                updateAssignment.mutate({
                  assignmentId: assignment.id,
                  data: { is_active: checked },
                })
              }
            />
            <span className="text-sm">{assignment.is_active ? "Active" : "Inactive"}</span>
          </div>
        ) : (
          <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
            {assignment.is_active ? "Active" : "Inactive"}
          </StatusBadge>
        ),
    },
    ...(canManageAssignments
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right" as const,
            headClassName: "w-12",
            cell: (assignment: PolicyAssignmentResponse) => (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove assignment"
                disabled={deleteAssignment.isPending}
                onClick={() => handleDeleteAssignment(assignment)}
              >
                <Trash2 />
              </Button>
            ),
          },
        ]
      : []),
  ];
  return (
    <PolicyCard
      title="Assignments"
      description="Entities currently using this policy."
      icon={ShieldCheck}
    >
      <div className="mb-3 flex justify-end">
        <Select value={scopeFilter} onValueChange={setScopeFilter}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All scopes</SelectItem>
            <SelectItem value="org">Organization</SelectItem>
            <SelectItem value="team">Teams</SelectItem>
            <SelectItem value="project">Projects</SelectItem>
            <SelectItem value="virtual_key">Virtual keys</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <DataTable
        columns={columns}
        data={filteredAssignments}
        getRowKey={(assignment) => assignment.id}
        empty={{
          title: "No assignments",
          description: "This policy is not assigned to this scope.",
        }}
      />
      {actionConfirmationDialog}
    </PolicyCard>
  );
}

function AccessPoliciesTable({
  policies,
  assignmentCount,
  isLoading,
  onConfigureRoutes,
  onEditPolicy,
  onAssign,
  canManageDefinition,
  canAssign,
}: {
  policies: AccessPolicyResponse[];
  assignmentCount: (policyId: string, type: "access") => number;
  isLoading: boolean;
  onConfigureRoutes: (policy: AccessPolicyResponse) => void;
  onEditPolicy: (policy: AccessPolicyResponse) => void;
  onAssign: (policy: AccessPolicyResponse) => void;
  canManageDefinition: (policy: AccessPolicyResponse) => boolean;
  canAssign: boolean;
}) {
  const queryClient = useQueryClient();
  const {
    requestImpactConfirmation,
    isLoadingImpact,
    dialog: impactConfirmationDialog,
  } = useImpactConfirmation();
  const deletePolicy = useDeleteAccessPolicyApiV1PoliciesAccessPolicyIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Access policy deleted.");
        await queryClient.invalidateQueries();
      },
      onError: () => toast.error("Access policy could not be deleted."),
    },
  });
  const handleDeletePolicy = async (policy: AccessPolicyResponse) => {
    await requestImpactConfirmation(
      `Delete access policy "${policy.name}"?`,
      () => getAccessPolicyImpactApiV1PoliciesAccessPolicyIdImpactGet(policy.id),
      () => deletePolicy.mutate({ policyId: policy.id }),
    );
  };
  const columns: DataTableColumn<AccessPolicyResponse>[] = [
    {
      key: "name",
      header: "Name",
      cell: (policy) => (
        <>
          <Link to={`/policies/access/${policy.id}`} className="font-medium hover:underline">
            {policy.name}
          </Link>
          <div className="text-xs text-muted-foreground">{policy.description}</div>
        </>
      ),
    },
    {
      key: "routes",
      header: "Routes",
      cell: (policy) => (
        <>
          <div>{policy.routes?.length ?? 0} routes</div>
          <div className="text-xs text-muted-foreground">{countRouteModels(policy)} models</div>
        </>
      ),
    },
    {
      key: "assignments",
      header: "Assignments",
      cell: (policy) => assignmentCount(policy.id, "access"),
    },
    {
      key: "status",
      header: "Status",
      cell: (policy) => {
        const status = accessPolicyStatus(policy, assignmentCount(policy.id, "access"));
        return <StatusBadge variant={status.variant}>{status.label}</StatusBadge>;
      },
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      headClassName: "w-36",
      cell: (policy) => {
        const canManage = canManageDefinition(policy);
        return (
          <div className="flex justify-end gap-1">
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Edit ${policy.name}`}
                onClick={() => onEditPolicy(policy)}
              >
                <Pencil />
              </Button>
            ) : null}
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Configure routes for ${policy.name}`}
                onClick={() => onConfigureRoutes(policy)}
              >
                <Route />
              </Button>
            ) : null}
            {canAssign ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Assign ${policy.name}`}
                onClick={() => onAssign(policy)}
              >
                <Plus />
              </Button>
            ) : null}
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${policy.name}`}
                disabled={isLoadingImpact || deletePolicy.isPending}
                onClick={() => void handleDeletePolicy(policy)}
              >
                <Trash2 />
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];
  return (
    <>
      <DataTable
        columns={columns}
        data={policies}
        loading={isLoading}
        getRowKey={(policy) => policy.id}
        empty={{ title: "No access policies", description: "Create a route policy first." }}
      />
      {impactConfirmationDialog}
    </>
  );
}

function LimitPoliciesTable({
  policies,
  assignmentCount,
  isLoading,
  onConfigureRules,
  onEditPolicy,
  onAssign,
  canManageDefinition,
  canAssign,
}: {
  policies: LimitPolicyResponse[];
  assignmentCount: (policyId: string, type: "limit") => number;
  isLoading: boolean;
  onConfigureRules: (policy: LimitPolicyResponse) => void;
  onEditPolicy: (policy: LimitPolicyResponse) => void;
  onAssign: (policy: LimitPolicyResponse) => void;
  canManageDefinition: (policy: LimitPolicyResponse) => boolean;
  canAssign: boolean;
}) {
  const queryClient = useQueryClient();
  const {
    requestImpactConfirmation,
    isLoadingImpact,
    dialog: impactConfirmationDialog,
  } = useImpactConfirmation();
  const deletePolicy = useDeleteLimitPolicyApiV1PoliciesLimitsPolicyIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Limit policy deleted.");
        await queryClient.invalidateQueries();
      },
      onError: () => toast.error("Limit policy could not be deleted."),
    },
  });
  const handleDeletePolicy = async (policy: LimitPolicyResponse) => {
    await requestImpactConfirmation(
      `Delete limit policy "${policy.name}"?`,
      () => getLimitPolicyImpactApiV1PoliciesLimitsPolicyIdImpactGet(policy.id),
      () => deletePolicy.mutate({ policyId: policy.id }),
    );
  };
  const columns: DataTableColumn<LimitPolicyResponse>[] = [
    {
      key: "name",
      header: "Name",
      cell: (policy) => (
        <>
          <Link to={`/policies/limits/${policy.id}`} className="font-medium hover:underline">
            {policy.name}
          </Link>
          <div className="text-xs text-muted-foreground">{policy.description}</div>
        </>
      ),
    },
    {
      key: "rules",
      header: "Rules",
      className: "text-xs text-muted-foreground",
      cell: (policy) => (
        <>
          {(policy.rules ?? []).length} rules
          {(policy.rules ?? []).slice(0, 2).map((rule) => (
            <div key={rule.id}>{formatRuleSummary(rule)}</div>
          ))}
        </>
      ),
    },
    {
      key: "assignments",
      header: "Assignments",
      cell: (policy) => assignmentCount(policy.id, "limit"),
    },
    {
      key: "status",
      header: "Status",
      cell: (policy) => {
        const status = limitPolicyStatus(policy, assignmentCount(policy.id, "limit"));
        return <StatusBadge variant={status.variant}>{status.label}</StatusBadge>;
      },
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      headClassName: "w-24",
      cell: (policy) => {
        const canManage = canManageDefinition(policy);
        return (
          <div className="flex justify-end gap-1">
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Edit ${policy.name}`}
                onClick={() => onEditPolicy(policy)}
              >
                <Pencil />
              </Button>
            ) : null}
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Configure rules for ${policy.name}`}
                onClick={() => onConfigureRules(policy)}
              >
                <SlidersHorizontal />
              </Button>
            ) : null}
            {canAssign ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Assign ${policy.name}`}
                onClick={() => onAssign(policy)}
              >
                <Plus />
              </Button>
            ) : null}
            {canManage ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${policy.name}`}
                disabled={isLoadingImpact || deletePolicy.isPending}
                onClick={() => void handleDeletePolicy(policy)}
              >
                <Trash2 />
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];
  return (
    <>
      <DataTable
        columns={columns}
        data={policies}
        loading={isLoading}
        getRowKey={(policy) => policy.id}
        empty={{ title: "No limit policies", description: "Create a budget or cap policy." }}
      />
      {impactConfirmationDialog}
    </>
  );
}

function PolicySettingsSheet({
  state,
  onOpenChange,
  onChanged,
}: {
  state: PolicySettingsSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  return (
    <Sheet open={Boolean(state)} onOpenChange={onOpenChange}>
      {state ? (
        <PolicySettingsSheetContent
          key={`${state.kind}:${state.policy.id}`}
          state={state}
          onOpenChange={onOpenChange}
          onChanged={onChanged}
        />
      ) : null}
    </Sheet>
  );
}

function PolicySettingsSheetContent({
  state,
  onOpenChange,
  onChanged,
}: {
  state: NonNullable<PolicySettingsSheetState>;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const [name, setName] = useState(state.policy.name);
  const [description, setDescription] = useState(state.policy.description ?? "");
  const [isActive, setIsActive] = useState(state.policy.is_active);
  const updateAccessPolicy = useUpdateAccessPolicyApiV1PoliciesAccessPolicyIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Access policy updated.");
        await onChanged();
        onOpenChange(false);
      },
      onError: () => toast.error("Access policy could not be updated."),
    },
  });
  const updateLimitPolicy = useUpdateLimitPolicyApiV1PoliciesLimitsPolicyIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Limit policy updated.");
        await onChanged();
        onOpenChange(false);
      },
      onError: () => toast.error("Limit policy could not be updated."),
    },
  });

  const submit = () => {
    if (!name.trim()) return;
    const data = {
      name: name.trim(),
      description: description.trim() || null,
      is_active: isActive,
    };
    if (state.kind === "access") {
      updateAccessPolicy.mutate({ policyId: state.policy.id, data });
      return;
    }
    updateLimitPolicy.mutate({ policyId: state.policy.id, data });
  };

  return (
    <SheetContent>
      <SheetHeader>
        <SheetTitle>Edit policy</SheetTitle>
        <SheetDescription>Update policy metadata and activation state.</SheetDescription>
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
        <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 p-3">
          <div>
            <div className="text-sm font-medium">Active</div>
            <p className="text-xs text-muted-foreground">
              Inactive policies remain assigned but do not affect runtime decisions.
            </p>
          </div>
          <Switch checked={isActive} onCheckedChange={setIsActive} />
        </div>
      </div>
      <SheetFooter>
        <Button
          onClick={submit}
          disabled={!name.trim() || updateAccessPolicy.isPending || updateLimitPolicy.isPending}
        >
          Save policy
        </Button>
        <SheetClose asChild>
          <Button variant="outline">Cancel</Button>
        </SheetClose>
      </SheetFooter>
    </SheetContent>
  );
}

function CreatePolicySheet({
  kind,
  onOpenChange,
  onCreated,
}: {
  kind: SheetKind;
  onOpenChange: (open: boolean) => void;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [limitType, setLimitType] = useState("requests");
  const [limitValue, setLimitValue] = useState("");
  const [intervalUnit, setIntervalUnit] = useState("day");
  const [intervalCount, setIntervalCount] = useState("1");
  const [limitRuleFilters, setLimitRuleFilters] = useState<LimitRuleFilterValue>(
    emptyLimitRuleFilters,
  );
  const [draftRules, setDraftRules] = useState<DraftLimitRule[]>([]);
  const [assignmentScope, setAssignmentScope] = useState("none");
  const [assignmentTeamId, setAssignmentTeamId] = useState("");
  const [assignmentProjectId, setAssignmentProjectId] = useState("");
  const [assignmentVirtualKeyId, setAssignmentVirtualKeyId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [draftRoutes, setDraftRoutes] = useState<DraftAccessRoute[]>([]);
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const virtualKeysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(assignmentProjectId, {
    query: { enabled: assignmentScope === "virtual_key" && Boolean(assignmentProjectId) },
  });
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const virtualKeys = virtualKeysQuery.data?.status === 200 ? virtualKeysQuery.data.data : [];
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    createAccessOptionsParams(
      assignmentScope,
      assignmentTeamId,
      assignmentProjectId,
      assignmentVirtualKeyId,
    ),
    {
      query: {
        enabled:
          kind === "access" &&
          assignmentTargetReady(
            assignmentScope,
            assignmentTeamId,
            assignmentProjectId,
            assignmentVirtualKeyId,
          ),
      },
    },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? (accessOptionsQuery.data.data.providers ?? []) : [];
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
  const createAccess = useCreateAccessPolicyApiV1PoliciesAccessPost();
  const createLimit = useCreateLimitPolicyApiV1PoliciesLimitsPost();
  const createAssignment = useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost();
  const isLimit = kind === "limit";
  const reset = () => {
    setName("");
    setDescription("");
    setLimitType("requests");
    setLimitValue("");
    setIntervalUnit("day");
    setIntervalCount("1");
    setLimitRuleFilters(emptyLimitRuleFilters());
    setDraftRules([]);
    setAssignmentScope("none");
    setAssignmentTeamId("");
    setAssignmentProjectId("");
    setAssignmentVirtualKeyId("");
    setProviderId("");
    setPoolId("");
    setSelectedModels([]);
    setDraftRoutes([]);
  };
  const currentRuleHasLimits = Boolean(limitValue.trim());
  const currentDraftRule = (): DraftLimitRule => ({
    id: crypto.randomUUID(),
    name: draftRules.length === 0 ? "Default rule" : `Rule ${draftRules.length + 1}`,
    limitType,
    limitValue,
    intervalUnit,
    intervalCount,
    filters: limitRuleFilters,
  });
  const addDraftRule = () => {
    if (!currentRuleHasLimits) return;
    setDraftRules((current) => [...current, currentDraftRule()]);
    setLimitValue("");
    setLimitRuleFilters(emptyLimitRuleFilters());
  };
  const ruleInput = (rule: DraftLimitRule) => ({
    name: rule.name,
    limit_type: rule.limitType,
    limit_value:
      rule.limitType === "budget_cents"
        ? Math.round(Number(rule.limitValue) * 100)
        : Number(rule.limitValue),
    interval_unit: rule.intervalUnit,
    interval_count: rule.intervalUnit === "lifetime" ? 1 : Number(rule.intervalCount || 1),
    is_active: true,
    ...limitRuleFiltersPayload(rule.filters),
  });
  const rulesForSubmit = () => {
    const rules = [...draftRules];
    if (currentRuleHasLimits) rules.push(currentDraftRule());
    return rules;
  };
  const currentAccessRoute = (): DraftAccessRoute | null => {
    const provider = accessOptions.find((option) => option.id === providerId);
    const pool = pools.find((option) => option.id === poolId);
    if (!provider || !pool || selectedModels.length === 0) return null;
    return {
      id: crypto.randomUUID(),
      providerId,
      providerLabel: provider.display_name,
      poolId,
      poolLabel: pool.name,
      modelIds: selectedModels,
    };
  };
  const accessRoutesForSubmit = () => {
    const currentRoute = currentAccessRoute();
    return currentRoute ? [...draftRoutes, currentRoute] : draftRoutes;
  };
  const assignmentPayload = (policyId: string) => {
    if (assignmentScope === "none") return null;
    return {
      policy_type: isLimit ? "limit" : "access",
      access_policy_id: isLimit ? null : policyId,
      limit_policy_id: isLimit ? policyId : null,
      scope_type: assignmentScope,
      team_id: assignmentScope === "team" ? assignmentTeamId : null,
      project_id: assignmentScope === "project" ? assignmentProjectId : null,
      virtual_key_id: assignmentScope === "virtual_key" ? assignmentVirtualKeyId : null,
      is_active: true,
    };
  };
  const submit = async () => {
    if (!name.trim()) return;
    try {
      let policyId = "";
      if (isLimit) {
        const rules = rulesForSubmit();
        if (rules.length === 0) return;
        const response = await createLimit.mutateAsync({
          data: {
            name,
            description: description || null,
            rules: rules.map(ruleInput),
          },
        });
        if (response.status !== 201) return;
        policyId = response.data.id;
      } else {
        const routes = accessRoutesForSubmit();
        if (routes.length === 0) return;
        const response = await createAccess.mutateAsync({
          data: {
            name,
            description: description || null,
            routes: routes.map(toAccessRouteInput),
          },
        });
        if (response.status !== 201) return;
        policyId = response.data.id;
      }
      const payload = assignmentPayload(policyId);
      if (payload) {
        await createAssignment.mutateAsync({ data: payload });
      }
      toast.success(payload ? "Policy created and assigned." : "Policy created.");
      reset();
      await onCreated();
    } catch {
      toast.error("Policy could not be created.");
    }
  };
  const canSubmit =
    Boolean(name.trim()) &&
    assignmentTargetReady(
      assignmentScope,
      assignmentTeamId,
      assignmentProjectId,
      assignmentVirtualKeyId,
    ) &&
    ((isLimit && (draftRules.length > 0 || currentRuleHasLimits)) ||
      (!isLimit &&
        (draftRoutes.length > 0 || (providerId && poolId && selectedModels.length > 0))));
  const addDraftRoute = () => {
    const route = currentAccessRoute();
    if (!route) return;
    setDraftRoutes((current) => [...current, route]);
    setProviderId("");
    setPoolId("");
    setSelectedModels([]);
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
          <SheetTitle>{isLimit ? "New limit policy" : "New access policy"}</SheetTitle>
          <SheetDescription>
            {isLimit
              ? "Create reusable caps and optionally assign them immediately."
              : "Create an initial route and optionally assign the policy immediately."}
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
          <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
            <div>
              <div className="text-sm font-medium">Initial assignment</div>
              <p className="text-xs text-muted-foreground">
                Leave unassigned for reusable policies managed only from policy details.
              </p>
            </div>
            <SelectField
              label="Scope"
              value={assignmentScope}
              onValueChange={(value) => {
                setAssignmentScope(value);
                setAssignmentTeamId("");
                setAssignmentProjectId("");
                setAssignmentVirtualKeyId("");
                setProviderId("");
                setPoolId("");
                setSelectedModels([]);
              }}
              options={["none", "org", "team", "project", "virtual_key"]}
              labels={{
                none: "Unassigned",
                org: "Organization",
                team: "Team",
                project: "Project",
                virtual_key: "Virtual key",
              }}
            />
            {assignmentScope === "team" ? (
              <SelectField
                label="Team"
                value={assignmentTeamId}
                onValueChange={setAssignmentTeamId}
                options={teams.map((team) => team.id)}
                labels={teamLabels(teams)}
              />
            ) : null}
            {assignmentScope === "project" || assignmentScope === "virtual_key" ? (
              <SelectField
                label="Project"
                value={assignmentProjectId}
                onValueChange={(value) => {
                  setAssignmentProjectId(value);
                  setAssignmentVirtualKeyId("");
                  setProviderId("");
                  setPoolId("");
                  setSelectedModels([]);
                }}
                options={projects.map((project) => project.id)}
                labels={projectLabels(projects)}
              />
            ) : null}
            {assignmentScope === "virtual_key" ? (
              <SelectField
                label="Virtual key"
                value={assignmentVirtualKeyId}
                onValueChange={(value) => {
                  setAssignmentVirtualKeyId(value);
                  setProviderId("");
                  setPoolId("");
                  setSelectedModels([]);
                }}
                options={virtualKeys.map((key) => key.id)}
                labels={Object.fromEntries(
                  virtualKeys.map((key) => [key.id, `${key.name} (${key.key_prefix})`]),
                )}
              />
            ) : null}
          </div>
          {!isLimit ? (
            <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
              <div>
                <div className="text-sm font-medium">Initial route</div>
                <p className="text-xs text-muted-foreground">
                  Add one or more provider pool and model routes.
                </p>
              </div>
              {draftRoutes.length > 0 ? (
                <div className="grid gap-2">
                  {draftRoutes.map((route) => (
                    <div
                      key={route.id}
                      className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="font-medium">
                          {route.providerLabel} / {route.poolLabel}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {route.modelIds.length} model
                          {route.modelIds.length === 1 ? "" : "s"}
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
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
              <SelectField
                label="Provider"
                value={providerId}
                onValueChange={(value) => {
                  const provider = accessOptions.find((option) => option.id === value);
                  const pool = provider?.pools?.[0];
                  setProviderId(value);
                  setPoolId(pool?.id ?? "");
                  setSelectedModels([]);
                }}
                options={accessOptions.map((provider) => provider.id)}
                labels={providerOptionLabels(accessOptions)}
                placeholder={accessOptionsQuery.isLoading ? "Loading providers" : "Choose provider"}
              />
              <SelectField
                label="Credential pool"
                value={poolId}
                onValueChange={(value) => {
                  setPoolId(value);
                  setSelectedModels([]);
                }}
                options={pools.map((pool) => pool.id)}
                labels={Object.fromEntries(pools.map((pool) => [pool.id, pool.name]))}
              />
              <ModelMultiselect
                models={models}
                selected={selectedModels}
                onChange={setSelectedModels}
                disabled={!poolId}
                isLoading={accessOptionsQuery.isLoading}
                isError={accessOptionsQuery.isError}
                placeholderHint="Choose a provider and pool to load model offerings."
                emptyHint="No model offerings are available for this pool."
              />
              <Button
                type="button"
                variant="outline"
                onClick={addDraftRoute}
                disabled={!providerId || !poolId || selectedModels.length === 0}
              >
                <Plus />
                Add route
              </Button>
            </div>
          ) : null}
          {isLimit ? (
            <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
              <div>
                <div className="text-sm font-medium">Rules</div>
                <p className="text-xs text-muted-foreground">
                  Add one rule at a time. Rules in the same policy are enforced together.
                </p>
              </div>
              {draftRules.length > 0 ? (
                <div className="grid gap-2">
                  {draftRules.map((rule) => (
                    <div
                      key={rule.id}
                      className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="font-medium">{rule.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {formatDraftRuleSummary(rule)}
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() =>
                          setDraftRules((current) =>
                            current.filter((candidate) => candidate.id !== rule.id),
                          )
                        }
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  ))}
                </div>
              ) : null}
              <LimitRuleFields
                limitType={limitType}
                onLimitTypeChange={setLimitType}
                limitValue={limitValue}
                onLimitValueChange={setLimitValue}
                intervalUnit={intervalUnit}
                onIntervalUnitChange={setIntervalUnit}
                intervalCount={intervalCount}
                onIntervalCountChange={setIntervalCount}
                filters={limitRuleFilters}
                onFiltersChange={setLimitRuleFilters}
              />
              <Button
                type="button"
                variant="outline"
                onClick={addDraftRule}
                disabled={!currentRuleHasLimits}
              >
                <Plus />
                Add another rule
              </Button>
            </div>
          ) : null}
        </div>
        <SheetFooter>
          <Button
            onClick={submit}
            disabled={
              !canSubmit ||
              createAccess.isPending ||
              createLimit.isPending ||
              createAssignment.isPending
            }
          >
            {assignmentScope === "none" ? "Create policy" : "Create and assign"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function RouteSheet({
  state,
  onOpenChange,
  onChanged,
}: {
  state: RouteSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [editingRoute, setEditingRoute] = useState<AccessPolicyRouteResponse | null>(null);
  const [priority, setPriority] = useState("100");
  const [weight, setWeight] = useState("100");
  const [routeIsActive, setRouteIsActive] = useState(true);
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    accessOptionsParamsForPolicy(state?.policy),
    { query: { enabled: Boolean(state) } },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? (accessOptionsQuery.data.data.providers ?? []) : [];
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
  const createRoute = useCreateAccessPolicyRouteApiV1PoliciesAccessPolicyIdRoutesPost({
    mutation: {
      onSuccess: async () => {
        toast.success("Access route added.");
        resetForm();
        await onChanged();
      },
      onError: () => toast.error("Access route could not be added."),
    },
  });
  const deleteRoute = useDeleteAccessPolicyRouteApiV1PoliciesAccessRoutesRouteIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Access route removed.");
        await onChanged();
      },
      onError: () => toast.error("Access route could not be removed."),
    },
  });
  const updateRoute = useUpdateAccessPolicyRouteApiV1PoliciesAccessRoutesRouteIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Access route updated.");
        resetForm();
        await onChanged();
      },
      onError: () => toast.error("Access route could not be updated."),
    },
  });
  const routeModelLabels = Object.fromEntries(
    models.map((model) => [model.id, model.provider_model_name]),
  );
  const resetForm = () => {
    setProviderId("");
    setPoolId("");
    setSelectedModels([]);
    setEditingRoute(null);
    setPriority("100");
    setWeight("100");
    setRouteIsActive(true);
  };
  const startEditRoute = (route: AccessPolicyRouteResponse) => {
    setEditingRoute(route);
    setProviderId(route.provider_id);
    setPoolId(route.credential_pool_id);
    setSelectedModels(route.model_offering_ids);
    setPriority(String(route.priority));
    setWeight(String(route.weight));
    setRouteIsActive(route.is_active);
  };
  const handleDeleteRoute = async (route: AccessPolicyRouteResponse) => {
    await requestImpactConfirmation(
      "Delete this access route?",
      () => getAccessPolicyRouteImpactApiV1PoliciesAccessRoutesRouteIdImpactGet(route.id),
      () => deleteRoute.mutate({ routeId: route.id }),
    );
  };
  const submit = () => {
    if (!state || !providerId || !poolId || selectedModels.length === 0) return;
    if (editingRoute) {
      updateRoute.mutate({
        routeId: editingRoute.id,
        data: {
          provider_id: providerId,
          credential_pool_id: poolId,
          model_offering_ids: selectedModels,
          priority: Number(priority) || 100,
          weight: Number(weight) || 100,
          is_active: routeIsActive,
        },
      });
      return;
    }
    createRoute.mutate({
      policyId: state.policy.id,
      data: {
        provider_id: providerId,
        credential_pool_id: poolId,
        model_offering_ids: selectedModels,
        priority: Number(priority) || 100,
        weight: Number(weight) || 100,
        is_active: routeIsActive,
      },
    });
  };
  const {
    requestImpactConfirmation,
    isLoadingImpact,
    dialog: impactConfirmationDialog,
  } = useImpactConfirmation();
  return (
    <Sheet open={Boolean(state)} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Configure access routes</SheetTitle>
          <SheetDescription>
            Routes choose a provider, one credential pool, and the model offerings this policy can
            serve.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {state ? (
            <div className="grid gap-5">
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Route</TableHead>
                      <TableHead>Priority</TableHead>
                      <TableHead>Tie-break weight</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-12" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(state.policy.routes ?? []).map((route) => (
                      <TableRow key={route.id}>
                        <TableCell>
                          <div className="text-sm font-medium">
                            {route.model_offering_ids.length} models
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {route.model_offering_ids
                              .map((id) => routeModelLabels[id] ?? id.slice(0, 8))
                              .join(", ")}
                          </div>
                        </TableCell>
                        <TableCell>{route.priority}</TableCell>
                        <TableCell>{route.weight}</TableCell>
                        <TableCell>
                          <StatusBadge variant={route.is_active ? "active" : "inactive"}>
                            {route.is_active ? "Active" : "Inactive"}
                          </StatusBadge>
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Edit route"
                            onClick={() => startEditRoute(route)}
                          >
                            <SlidersHorizontal />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Delete route"
                            disabled={isLoadingImpact || deleteRoute.isPending}
                            onClick={() => void handleDeleteRoute(route)}
                          >
                            <Trash2 />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="grid gap-4 rounded-md border bg-muted/20 p-3">
                <div>
                  <div className="font-medium">{editingRoute ? "Edit route" : "Add route"}</div>
                  <p className="text-sm text-muted-foreground">
                    Routes can be reused anywhere this access policy is assigned.
                  </p>
                </div>
                <SelectField
                  label="Provider"
                  value={providerId}
                  onValueChange={(value) => {
                    const provider = accessOptions.find((option) => option.id === value);
                    const pool = provider?.pools?.[0];
                    setProviderId(value);
                    setPoolId(pool?.id ?? "");
                    setSelectedModels([]);
                  }}
                  options={accessOptions.map((provider) => provider.id)}
                  labels={providerOptionLabels(accessOptions)}
                  placeholder="Choose provider"
                />
                <SelectField
                  label="Credential pool"
                  value={poolId}
                  onValueChange={(value) => {
                    setPoolId(value);
                    setSelectedModels([]);
                  }}
                  options={pools.map((pool) => pool.id)}
                  labels={Object.fromEntries(pools.map((pool) => [pool.id, pool.name]))}
                  placeholder="Choose pool"
                />
                <ModelMultiselect
                  models={models}
                  selected={selectedModels}
                  onChange={setSelectedModels}
                  disabled={!providerId}
                  isLoading={accessOptionsQuery.isLoading}
                  isError={accessOptionsQuery.isError}
                />
                <div className="grid items-start gap-3 sm:grid-cols-2">
                  <Field label="Priority">
                    <Input value={priority} onChange={(event) => setPriority(event.target.value)} />
                  </Field>
                  <Field label="Weight">
                    <Input value={weight} onChange={(event) => setWeight(event.target.value)} />
                    <p className="text-xs text-muted-foreground">
                      Higher weight wins when priority ties; it does not split traffic.
                    </p>
                  </Field>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-3">
                  <div>
                    <div className="text-sm font-medium">Active</div>
                    <p className="text-xs text-muted-foreground">
                      Inactive routes remain configured but are skipped at runtime.
                    </p>
                  </div>
                  <Switch checked={routeIsActive} onCheckedChange={setRouteIsActive} />
                </div>
              </div>
            </div>
          ) : null}
        </div>
        <SheetFooter>
          <Button
            onClick={submit}
            disabled={
              !providerId ||
              !poolId ||
              selectedModels.length === 0 ||
              createRoute.isPending ||
              updateRoute.isPending
            }
          >
            {editingRoute ? "Save route" : "Add route"}
          </Button>
          {editingRoute ? (
            <Button type="button" variant="outline" onClick={resetForm}>
              Cancel edit
            </Button>
          ) : null}
          <SheetClose asChild>
            <Button variant="outline">Close</Button>
          </SheetClose>
        </SheetFooter>
        {impactConfirmationDialog}
      </SheetContent>
    </Sheet>
  );
}

function LimitRulesSheet({
  state,
  onOpenChange,
  onChanged,
}: {
  state: LimitRulesSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const [editingRule, setEditingRule] = useState<LimitPolicyRuleResponse | null>(null);
  const [name, setName] = useState("Rule");
  const [limitType, setLimitType] = useState("requests");
  const [limitValue, setLimitValue] = useState("");
  const [intervalUnit, setIntervalUnit] = useState("day");
  const [intervalCount, setIntervalCount] = useState("1");
  const [ruleIsActive, setRuleIsActive] = useState(true);
  const [ruleFilters, setRuleFilters] = useState<LimitRuleFilterValue>(emptyLimitRuleFilters);
  const {
    requestImpactConfirmation,
    isLoadingImpact,
    dialog: impactConfirmationDialog,
  } = useImpactConfirmation();
  const createRule = useCreateLimitPolicyRuleApiV1PoliciesLimitsPolicyIdRulesPost({
    mutation: {
      onSuccess: async () => {
        toast.success("Limit rule added.");
        await onChanged();
        resetForm();
      },
      onError: () => toast.error("Limit rule could not be added."),
    },
  });
  const updateRule = useUpdateLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdPatch({
    mutation: {
      onSuccess: async () => {
        toast.success("Limit rule updated.");
        await onChanged();
        resetForm();
      },
      onError: () => toast.error("Limit rule could not be updated."),
    },
  });
  const deleteRule = useDeleteLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdDelete({
    mutation: {
      onSuccess: async () => {
        toast.success("Limit rule removed.");
        await onChanged();
      },
      onError: () => toast.error("Limit rule could not be removed."),
    },
  });
  const resetForm = () => {
    setEditingRule(null);
    setName("Rule");
    setLimitType("requests");
    setLimitValue("");
    setIntervalUnit("day");
    setIntervalCount("1");
    setRuleIsActive(true);
    setRuleFilters(emptyLimitRuleFilters());
  };
  const startEdit = (rule: LimitPolicyRuleResponse) => {
    setEditingRule(rule);
    setName(rule.name);
    setLimitType(rule.limit_type);
    setLimitValue(
      rule.limit_type === "budget_cents"
        ? String(rule.limit_value / 100)
        : String(rule.limit_value),
    );
    setIntervalUnit(rule.interval_unit);
    setIntervalCount(String(rule.interval_count));
    setRuleIsActive(rule.is_active);
    setRuleFilters({
      providerId: rule.provider_id ?? "",
      poolId: rule.credential_pool_id ?? "",
      modelId: rule.model_offering_id ?? "",
      accessPolicyId: rule.access_policy_id ?? "",
    });
  };
  const handleDeleteRule = async (rule: LimitPolicyRuleResponse) => {
    await requestImpactConfirmation(
      `Delete limit rule "${rule.name}"?`,
      () => getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet(rule.id),
      () => deleteRule.mutate({ ruleId: rule.id }),
    );
  };
  const rulePayload = {
    name,
    limit_type: limitType,
    limit_value:
      limitType === "budget_cents" ? Math.round(Number(limitValue) * 100) : Number(limitValue),
    interval_unit: intervalUnit,
    interval_count: intervalUnit === "lifetime" ? 1 : Number(intervalCount || 1),
    is_active: ruleIsActive,
    ...limitRuleFiltersPayload(ruleFilters),
  };
  const hasAnyLimit = Boolean(limitValue.trim());
  const submit = () => {
    if (!state || !name.trim() || !hasAnyLimit) return;
    if (editingRule) {
      updateRule.mutate({ ruleId: editingRule.id, data: rulePayload });
      return;
    }
    createRule.mutate({ policyId: state.policy.id, data: rulePayload });
  };
  return (
    <Sheet
      open={Boolean(state)}
      onOpenChange={(open) => {
        if (!open) resetForm();
        onOpenChange(open);
      }}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Configure limit rules</SheetTitle>
          <SheetDescription>
            Limit policies are reusable. Rules define the concrete budgets, request caps, and token
            caps.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {state ? (
            <div className="grid gap-5">
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Rule</TableHead>
                      <TableHead>Interval</TableHead>
                      <TableHead>Limit</TableHead>
                      <TableHead>Filters</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-20" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(state.policy.rules ?? []).map((rule) => (
                      <TableRow key={rule.id}>
                        <TableCell className="font-medium">{rule.name}</TableCell>
                        <TableCell>
                          {formatInterval(rule.interval_unit, rule.interval_count)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatRuleSummary(rule)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          <LimitRuleFiltersSummary rule={rule} />
                        </TableCell>
                        <TableCell>
                          <StatusBadge variant={rule.is_active ? "active" : "inactive"}>
                            {rule.is_active ? "Active" : "Inactive"}
                          </StatusBadge>
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Edit ${rule.name}`}
                              onClick={() => startEdit(rule)}
                            >
                              <SlidersHorizontal />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Delete ${rule.name}`}
                              disabled={isLoadingImpact || deleteRule.isPending}
                              onClick={() => void handleDeleteRule(rule)}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="grid gap-4 rounded-md border bg-muted/20 p-3">
                <div>
                  <div className="font-medium">{editingRule ? "Edit rule" : "Add rule"}</div>
                  <p className="text-sm text-muted-foreground">
                    Add one budget or cap window per rule. Matching rules compose at runtime.
                  </p>
                </div>
                <Field label="Rule name">
                  <Input value={name} onChange={(event) => setName(event.target.value)} />
                </Field>
                <LimitRuleFields
                  limitType={limitType}
                  onLimitTypeChange={setLimitType}
                  limitValue={limitValue}
                  onLimitValueChange={setLimitValue}
                  intervalUnit={intervalUnit}
                  onIntervalUnitChange={setIntervalUnit}
                  intervalCount={intervalCount}
                  onIntervalCountChange={setIntervalCount}
                  filters={ruleFilters}
                  onFiltersChange={setRuleFilters}
                />
                <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-3">
                  <div>
                    <div className="text-sm font-medium">Active</div>
                    <p className="text-xs text-muted-foreground">
                      Inactive rules remain configured but are skipped at runtime.
                    </p>
                  </div>
                  <Switch checked={ruleIsActive} onCheckedChange={setRuleIsActive} />
                </div>
              </div>
            </div>
          ) : null}
        </div>
        <SheetFooter>
          <Button
            onClick={submit}
            disabled={!name.trim() || !hasAnyLimit || createRule.isPending || updateRule.isPending}
          >
            {editingRule ? "Save rule" : "Add rule"}
          </Button>
          {editingRule ? (
            <Button type="button" variant="outline" onClick={resetForm}>
              Cancel edit
            </Button>
          ) : null}
          <SheetClose asChild>
            <Button variant="outline">Close</Button>
          </SheetClose>
        </SheetFooter>
        {impactConfirmationDialog}
      </SheetContent>
    </Sheet>
  );
}

function AssignmentSheet({
  state,
  onOpenChange,
  onChanged,
  canAssignOrg,
}: {
  state: AssignmentSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
  canAssignOrg: boolean;
}) {
  const [scopeType, setScopeType] = useState(canAssignOrg ? "org" : "project");
  const [scopeId, setScopeId] = useState("");
  const currentUserQuery = useMeApiV1AuthMeGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teamAdminIds = new Set(
    (currentUser?.team_memberships ?? [])
      .filter((membership) => membership.role === "team_admin")
      .map((membership) => membership.team_id),
  );
  const projectAdminIds = new Set(
    (currentUser?.project_memberships ?? [])
      .filter((membership) => membership.role === "project_admin")
      .map((membership) => membership.project_id),
  );
  const assignableTeams = canAssignOrg ? teams : teams.filter((team) => teamAdminIds.has(team.id));
  const assignableProjects = canAssignOrg
    ? projects
    : projects.filter(
        (project) => teamAdminIds.has(project.team_id) || projectAdminIds.has(project.id),
      );
  const scopeOptions = [
    ...(canAssignOrg ? ["org"] : []),
    ...(assignableTeams.length ? ["team"] : []),
    ...(assignableProjects.length ? ["project", "virtual_key"] : []),
  ];
  const createAssignment = useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost({
    mutation: {
      onSuccess: async () => {
        toast.success("Policy assigned.");
        await onChanged();
        onOpenChange(false);
      },
      onError: () => toast.error("Policy could not be assigned."),
    },
  });
  const submit = () => {
    if (!state) return;
    if (scopeType !== "org" && !scopeId.trim()) return;
    createAssignment.mutate({
      data: {
        policy_type: state.policyType,
        access_policy_id: state.policyType === "access" ? state.policyId : null,
        limit_policy_id: state.policyType === "limit" ? state.policyId : null,
        scope_type: scopeType,
        team_id: scopeType === "team" ? scopeId : null,
        project_id: scopeType === "project" ? scopeId : null,
        virtual_key_id: scopeType === "virtual_key" ? scopeId : null,
        is_active: true,
      },
    });
  };
  return (
    <Sheet
      open={Boolean(state)}
      onOpenChange={(open) => {
        if (!open) {
          setScopeType(canAssignOrg ? "org" : "project");
          setScopeId("");
        }
        onOpenChange(open);
      }}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Assign policy</SheetTitle>
          <SheetDescription>
            Assignments are the only way access and limit policies become effective.
          </SheetDescription>
        </SheetHeader>
        <div className="grid gap-4 overflow-y-auto px-6 py-5">
          <SelectField
            label="Scope"
            value={scopeType}
            onValueChange={(value) => {
              setScopeType(value);
              setScopeId("");
            }}
            options={scopeOptions}
            labels={{
              org: "Organization",
              team: "Team",
              project: "Project",
              virtual_key: "Virtual key",
            }}
          />
          {scopeType === "team" ? (
            <SelectField
              label="Team"
              value={scopeId}
              onValueChange={setScopeId}
              options={assignableTeams.map((team) => team.id)}
              labels={teamLabels(assignableTeams)}
            />
          ) : null}
          {scopeType === "project" ? (
            <SelectField
              label="Project"
              value={scopeId}
              onValueChange={setScopeId}
              options={assignableProjects.map((project) => project.id)}
              labels={projectLabels(assignableProjects)}
            />
          ) : null}
          {scopeType === "virtual_key" ? (
            <Field label="Virtual key ID">
              <Input
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                placeholder="Paste the virtual key id"
              />
            </Field>
          ) : null}
        </div>
        <SheetFooter>
          <Button onClick={submit} disabled={scopeType !== "org" && !scopeId.trim()}>
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function SelectField({
  label,
  value,
  onValueChange,
  options,
  labels = {},
  placeholder = "Choose",
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: string[];
  labels?: Record<string, string>;
  placeholder?: string;
}) {
  return (
    <Field label={label}>
      <Select value={value} onValueChange={onValueChange} disabled={options.length === 0}>
        <SelectTrigger>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              <span className="block max-w-[34rem] truncate">{labels[option] ?? option}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}

function LimitRuleFields({
  limitType,
  onLimitTypeChange,
  limitValue,
  onLimitValueChange,
  intervalUnit,
  onIntervalUnitChange,
  intervalCount,
  onIntervalCountChange,
  filters,
  onFiltersChange,
}: {
  limitType: string;
  onLimitTypeChange: (value: string) => void;
  limitValue: string;
  onLimitValueChange: (value: string) => void;
  intervalUnit: string;
  onIntervalUnitChange: (value: string) => void;
  intervalCount: string;
  onIntervalCountChange: (value: string) => void;
  filters: LimitRuleFilterValue;
  onFiltersChange: (value: LimitRuleFilterValue) => void;
}) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
        <Field label="Every">
          <Input
            type="number"
            min={1}
            value={intervalCount}
            disabled={intervalUnit === "lifetime"}
            onChange={(event) => onIntervalCountChange(event.target.value)}
          />
        </Field>
        <SelectField
          label="Interval"
          value={intervalUnit}
          onValueChange={onIntervalUnitChange}
          options={["minute", "hour", "day", "week", "month", "lifetime"]}
          labels={{
            minute: "Minute",
            hour: "Hour",
            day: "Day",
            week: "Week",
            month: "Month",
            lifetime: "Lifetime",
          }}
        />
      </div>
      <SelectField
        label="Limit type"
        value={limitType}
        onValueChange={onLimitTypeChange}
        options={limitTypeOptions.map((option) => option.value)}
        labels={Object.fromEntries(limitTypeOptions.map((option) => [option.value, option.label]))}
      />
      <Field label={limitType === "budget_cents" ? "Amount ($)" : "Value"}>
        <Input
          type="number"
          min={1}
          value={limitValue}
          onChange={(event) => onLimitValueChange(event.target.value)}
        />
      </Field>
      <LimitRuleFilterFields value={filters} onChange={onFiltersChange} />
    </>
  );
}

function formatRuleSummary(rule: LimitPolicyRuleResponse) {
  const typeLabel =
    limitTypeOptions.find((option) => option.value === rule.limit_type)?.label ?? rule.limit_type;
  const value =
    rule.limit_type === "budget_cents"
      ? `$${(rule.limit_value / 100).toLocaleString()}`
      : rule.limit_value.toLocaleString();
  return `${typeLabel}: ${value}`;
}

function formatDraftRuleSummary(rule: DraftLimitRule) {
  const typeLabel =
    limitTypeOptions.find((option) => option.value === rule.limitType)?.label ?? rule.limitType;
  const value =
    rule.limitType === "budget_cents"
      ? `$${Number(rule.limitValue).toLocaleString()}`
      : Number(rule.limitValue).toLocaleString();
  const filterSummary = formatDraftRuleFilters(rule.filters);
  return `${typeLabel}: ${value} ${formatInterval(rule.intervalUnit, rule.intervalCount)}${filterSummary ? ` · ${filterSummary}` : ""}`;
}

function toAccessRouteInput(route: DraftAccessRoute): AccessPolicyRouteInput {
  return {
    provider_id: route.providerId,
    credential_pool_id: route.poolId,
    model_offering_ids: route.modelIds,
  };
}

function formatDraftRuleFilters(filters: LimitRuleFilterValue) {
  const activeFilters = [
    filters.providerId ? "provider" : null,
    filters.poolId ? "pool" : null,
    filters.modelId ? "model" : null,
    filters.accessPolicyId ? "access policy" : null,
  ].filter(Boolean);
  return activeFilters.length ? `filtered by ${activeFilters.join(", ")}` : "";
}

function countRouteModels(policy: AccessPolicyResponse) {
  return (policy.routes ?? []).reduce((total, route) => total + route.model_offering_ids.length, 0);
}

function teamLabels(teams: TeamResponse[]) {
  return Object.fromEntries(teams.map((team) => [team.id, team.name]));
}

function projectLabels(projects: ProjectResponse[]) {
  return Object.fromEntries(projects.map((project) => [project.id, project.name]));
}

function providerOptionLabels(providers: AccessPolicyProviderOption[]) {
  return Object.fromEntries(providers.map((provider) => [provider.id, provider.display_name]));
}

function assignmentTargetReady(
  scopeType: string,
  teamId: string,
  projectId: string,
  virtualKeyId: string,
) {
  if (scopeType === "team") return Boolean(teamId);
  if (scopeType === "project") return Boolean(projectId);
  if (scopeType === "virtual_key") return Boolean(projectId && virtualKeyId);
  return true;
}

function createAccessOptionsParams(
  scopeType: string,
  teamId: string,
  projectId: string,
  virtualKeyId: string,
) {
  if (scopeType === "team") return { scope_type: "team", team_id: teamId };
  if (scopeType === "project") return { scope_type: "project", project_id: projectId };
  if (scopeType === "virtual_key") {
    return {
      scope_type: "virtual_key",
      project_id: projectId,
      virtual_key_id: virtualKeyId,
    };
  }
  return { scope_type: "org" };
}

function accessOptionsParamsForPolicy(policy?: AccessPolicyResponse) {
  if (!policy) return { scope_type: "org" };
  if (policy.owning_scope_type === "team" && policy.owning_team_id) {
    return {
      scope_type: "team",
      team_id: policy.owning_team_id,
      exclude_policy_id: policy.id,
    };
  }
  if (policy.owning_scope_type === "project" && policy.owning_project_id) {
    return {
      scope_type: "project",
      project_id: policy.owning_project_id,
      exclude_policy_id: policy.id,
    };
  }
  if (policy.owning_scope_type === "virtual_key" && policy.owning_virtual_key_id) {
    return {
      scope_type: "virtual_key",
      project_id: policy.owning_project_id ?? undefined,
      virtual_key_id: policy.owning_virtual_key_id,
      exclude_policy_id: policy.id,
    };
  }
  return { scope_type: "org", exclude_policy_id: policy.id };
}

function formatInterval(intervalUnit: string, intervalCount: string | number) {
  if (intervalUnit === "lifetime") return "over lifetime";
  const count = Number(intervalCount) || 1;
  return `every ${count} ${intervalUnit}${count === 1 ? "" : "s"}`;
}
