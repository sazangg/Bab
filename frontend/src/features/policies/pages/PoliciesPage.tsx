import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  useUpdateAccessPolicyRouteApiV1PoliciesAccessRoutesRouteIdPatch,
  useUpdateLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdPatch,
} from "@/shared/api/generated/policies/policies";
import { hasAnyProjectAdminMembership, hasAnyTeamAdminMembership, hasPermission } from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";
import type {
  AccessPolicyResponse,
  AccessPolicyProviderOption,
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
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

type SheetKind = "access" | "limit" | null;
type RouteSheetState = { policy: AccessPolicyResponse } | null;
type LimitRulesSheetState = { policy: LimitPolicyResponse } | null;
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
};

const limitTypeOptions = [
  { value: "budget_cents", label: "Spend budget" },
  { value: "requests", label: "Request count" },
  { value: "input_tokens", label: "Input tokens" },
  { value: "output_tokens", label: "Output tokens" },
  { value: "total_tokens", label: "Total tokens" },
  { value: "tokens_per_request", label: "Tokens per request" },
];

async function confirmPolicyImpact(
  title: string,
  fetchImpact: () => Promise<{ status: number; data: unknown }>,
) {
  const response = await fetchImpact();
  if (response.status !== 200) {
    toast.error("Impact preview could not be loaded.");
    return false;
  }
  return window.confirm(formatPolicyImpactPreview(title, response.data as PolicyImpactResponse));
}

function formatPolicyImpactPreview(title: string, impact: PolicyImpactResponse) {
  const lines = [
    title,
    "",
    `Affected teams: ${impact.affected_team_count ?? 0}`,
    `Affected projects: ${impact.affected_project_count ?? 0}`,
    `Affected virtual keys: ${impact.affected_virtual_key_count ?? 0}`,
  ];
  const unusableKeys = impact.virtual_keys_would_become_unusable ?? [];
  if ((impact.virtual_keys_would_become_unusable_count ?? 0) > 0) {
    lines.push(
      `Virtual keys that would become unusable: ${impact.virtual_keys_would_become_unusable_count ?? 0}`,
      ...unusableKeys.slice(0, 5).map((key) => `- ${key.name}`),
    );
  }
  return lines.join("\n");
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
              onAssign={(policy) =>
                setAssignmentSheet({ policyType: "limit", policyId: policy.id })
              }
              canManageDefinitions={canManagePolicies}
              canAssign={canAssignPolicies}
            />
          ) : (
            <AccessPoliciesTable
              policies={filteredAccessPolicies}
              assignmentCount={assignmentCount}
              isLoading={accessQuery.isPending}
              onConfigureRoutes={(policy) => setRouteSheet({ policy })}
              onAssign={(policy) =>
                setAssignmentSheet({ policyType: "access", policyId: policy.id })
              }
              canManageDefinitions={canManagePolicies}
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
        state={routeSheet}
        onOpenChange={(open) => !open && setRouteSheet(null)}
        onChanged={invalidatePolicies}
      />
      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
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
    return <EmptyState title="Access policy not found" description="The policy may have been removed." />;
  }

  const routeCount = policy.routes?.length ?? 0;
  const modelCount = countRouteModels(policy);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
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
              <Button variant="outline" onClick={() => setAssignmentSheet({ policyType: "access", policyId })}>
                <Plus />
                Assign
              </Button>
            ) : null}
            {canManagePolicies ? (
              <Button onClick={() => setRouteSheet({ policy })}>
                <Route />
                Configure routes
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Routes" value={routeCount} />
        <MetricCard label="Models" value={modelCount} />
        <MetricCard label="Assignments" value={assignments.length} />
        <MetricCard label="Status" value={policy.is_active ? "Active" : "Inactive"} />
      </div>

      <PolicyCard title="Access routes" description="Routes decide which provider pool can serve selected models." icon={Route}>
        <AccessRoutesDetailTable routes={policy.routes ?? []} />
      </PolicyCard>

      <PolicyAssignmentsSection
        assignments={assignments}
        onChanged={invalidatePolicies}
        canManageAssignments={canAssignPolicies}
      />

      <RouteSheet
        state={routeSheet}
        onOpenChange={(open) => !open && setRouteSheet(null)}
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

export function LimitPolicyDetailPage() {
  const { policyId = "" } = useParams();
  const queryClient = useQueryClient();
  const [limitRulesSheet, setLimitRulesSheet] = useState<LimitRulesSheetState>(null);
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
    return <EmptyState title="Limit policy not found" description="The policy may have been removed." />;
  }

  const rules = policy.rules ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
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
              <Button variant="outline" onClick={() => setAssignmentSheet({ policyType: "limit", policyId })}>
                <Plus />
                Assign
              </Button>
            ) : null}
            {canManagePolicies ? (
              <Button onClick={() => setLimitRulesSheet({ policy })}>
                <SlidersHorizontal />
                Manage rules
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Rules" value={rules.length} />
        <MetricCard label="Assignments" value={assignments.length} />
        <MetricCard label="Active rules" value={rules.filter((rule) => rule.is_active).length} />
        <MetricCard label="Status" value={policy.is_active ? "Active" : "Inactive"} />
      </div>

      <PolicyCard title="Limit rules" description="Rules compose across matching scopes and dimensions." icon={SlidersHorizontal}>
        <LimitRulesDetailTable rules={rules} />
      </PolicyCard>

      <PolicyAssignmentsSection
        assignments={assignments}
        onChanged={invalidatePolicies}
        canManageAssignments={canAssignPolicies}
      />

      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
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

function MetricCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}

function AccessRoutesDetailTable({ routes }: { routes: AccessPolicyRouteResponse[] }) {
  if (routes.length === 0) {
    return (
      <EmptyState
        title="No routes configured"
        description="Add at least one provider pool and model route before assigning this policy."
      />
    );
  }
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Route</TableHead>
            <TableHead>Model offerings</TableHead>
            <TableHead>Routing</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {routes.map((route) => (
            <TableRow key={route.id}>
              <TableCell>
                <RouteProviderPool route={route} />
              </TableCell>
              <TableCell>
                <RouteModelNames route={route} />
              </TableCell>
              <TableCell className="text-sm">
                Priority {route.priority}
                <div className="text-xs text-muted-foreground">Weight {route.weight}</div>
              </TableCell>
              <TableCell>
                <StatusBadge variant={route.is_active ? "active" : "inactive"}>
                  {route.is_active ? "Active" : "Inactive"}
                </StatusBadge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
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
  if (rules.length === 0) {
    return (
      <EmptyState
        title="No rules configured"
        description="Add budget, request, or token rules before assigning this policy."
      />
    );
  }
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Rule</TableHead>
            <TableHead>Interval</TableHead>
            <TableHead>Limit</TableHead>
            <TableHead>Filters</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rules.map((rule) => (
            <TableRow key={rule.id}>
              <TableCell className="font-medium">{rule.name}</TableCell>
              <TableCell>{formatInterval(rule.interval_unit, rule.interval_count)}</TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {formatRuleSummary(rule)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatRuleFilters(rule)}
              </TableCell>
              <TableCell>
                <StatusBadge variant={rule.is_active ? "active" : "inactive"}>
                  {rule.is_active ? "Active" : "Inactive"}
                </StatusBadge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
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
  const handleDeleteAssignment = async (assignment: PolicyAssignmentResponse) => {
    if (!window.confirm("Remove this policy assignment?")) return;
    deleteAssignment.mutate({ assignmentId: assignment.id });
  };
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
      {filteredAssignments.length === 0 ? (
        <EmptyState title="No assignments" description="This policy is not assigned to this scope." />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scope</TableHead>
                <TableHead>Status</TableHead>
                {canManageAssignments ? <TableHead className="w-12" /> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredAssignments.map((assignment) => (
                <TableRow key={assignment.id}>
                  <TableCell>
                    <div className="capitalize">{assignment.scope_type.replace("_", " ")}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatAssignmentTarget(assignment, teamNames, projectNames)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
                      {assignment.is_active ? "Active" : "Inactive"}
                    </StatusBadge>
                  </TableCell>
                  {canManageAssignments ? (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Remove assignment"
                        onClick={() => void handleDeleteAssignment(assignment)}
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </PolicyCard>
  );
}

function AccessPoliciesTable({
  policies,
  assignmentCount,
  isLoading,
  onConfigureRoutes,
  onAssign,
  canManageDefinitions,
  canAssign,
}: {
  policies: AccessPolicyResponse[];
  assignmentCount: (policyId: string, type: "access") => number;
  isLoading: boolean;
  onConfigureRoutes: (policy: AccessPolicyResponse) => void;
  onAssign: (policy: AccessPolicyResponse) => void;
  canManageDefinitions: boolean;
  canAssign: boolean;
}) {
  const queryClient = useQueryClient();
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
    const confirmed = await confirmPolicyImpact(`Delete access policy "${policy.name}"?`, () =>
      getAccessPolicyImpactApiV1PoliciesAccessPolicyIdImpactGet(policy.id),
    );
    if (confirmed) deletePolicy.mutate({ policyId: policy.id });
  };
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading policies...</p>;
  if (policies.length === 0) {
    return <EmptyState title="No access policies" description="Create a route policy first." />;
  }
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Routes</TableHead>
            <TableHead>Assignments</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-36" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {policies.map((policy) => {
            const status = accessPolicyStatus(policy, assignmentCount(policy.id, "access"));
            return (
            <TableRow key={policy.id}>
              <TableCell>
                <Link to={`/policies/access/${policy.id}`} className="font-medium hover:underline">
                  {policy.name}
                </Link>
                <div className="text-xs text-muted-foreground">{policy.description}</div>
              </TableCell>
              <TableCell>
                <div>{policy.routes?.length ?? 0} routes</div>
                <div className="text-xs text-muted-foreground">
                  {countRouteModels(policy)} models
                </div>
              </TableCell>
              <TableCell>{assignmentCount(policy.id, "access")}</TableCell>
              <TableCell>
                <StatusBadge variant={status.variant}>{status.label}</StatusBadge>
              </TableCell>
              <TableCell>
                <div className="flex justify-end gap-1">
                  {canManageDefinitions ? (
                    <Button variant="ghost" size="icon" onClick={() => onConfigureRoutes(policy)}>
                      <Route />
                    </Button>
                  ) : null}
                  {canAssign ? (
                    <Button variant="ghost" size="icon" onClick={() => onAssign(policy)}>
                      <Plus />
                    </Button>
                  ) : null}
                  {canManageDefinitions ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${policy.name}`}
                      onClick={() => void handleDeletePolicy(policy)}
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          )})}
        </TableBody>
      </Table>
    </div>
  );
}

function LimitPoliciesTable({
  policies,
  assignmentCount,
  isLoading,
  onConfigureRules,
  onAssign,
  canManageDefinitions,
  canAssign,
}: {
  policies: LimitPolicyResponse[];
  assignmentCount: (policyId: string, type: "limit") => number;
  isLoading: boolean;
  onConfigureRules: (policy: LimitPolicyResponse) => void;
  onAssign: (policy: LimitPolicyResponse) => void;
  canManageDefinitions: boolean;
  canAssign: boolean;
}) {
  const queryClient = useQueryClient();
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
    const confirmed = await confirmPolicyImpact(`Delete limit policy "${policy.name}"?`, () =>
      getLimitPolicyImpactApiV1PoliciesLimitsPolicyIdImpactGet(policy.id),
    );
    if (confirmed) deletePolicy.mutate({ policyId: policy.id });
  };
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading policies...</p>;
  if (policies.length === 0) {
    return <EmptyState title="No limit policies" description="Create a budget or cap policy." />;
  }
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Rules</TableHead>
            <TableHead>Assignments</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {policies.map((policy) => {
            const status = limitPolicyStatus(policy, assignmentCount(policy.id, "limit"));
            return (
            <TableRow key={policy.id}>
              <TableCell>
                <Link to={`/policies/limits/${policy.id}`} className="font-medium hover:underline">
                  {policy.name}
                </Link>
                <div className="text-xs text-muted-foreground">{policy.description}</div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {(policy.rules ?? []).length} rules
                {(policy.rules ?? []).slice(0, 2).map((rule) => (
                  <div key={rule.id}>{formatRuleSummary(rule)}</div>
                ))}
              </TableCell>
              <TableCell>{assignmentCount(policy.id, "limit")}</TableCell>
              <TableCell>
                <StatusBadge variant={status.variant}>{status.label}</StatusBadge>
              </TableCell>
              <TableCell>
                <div className="flex justify-end gap-1">
                  {canManageDefinitions ? (
                    <Button variant="ghost" size="icon" onClick={() => onConfigureRules(policy)}>
                      <SlidersHorizontal />
                    </Button>
                  ) : null}
                  {canAssign ? (
                    <Button variant="ghost" size="icon" onClick={() => onAssign(policy)}>
                      <Plus />
                    </Button>
                  ) : null}
                  {canManageDefinitions ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${policy.name}`}
                      onClick={() => void handleDeletePolicy(policy)}
                    >
                      <Trash2 />
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          )})}
        </TableBody>
      </Table>
    </div>
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
  const [draftRules, setDraftRules] = useState<DraftLimitRule[]>([]);
  const [assignmentScope, setAssignmentScope] = useState("none");
  const [assignmentTeamId, setAssignmentTeamId] = useState("");
  const [assignmentProjectId, setAssignmentProjectId] = useState("");
  const [assignmentVirtualKeyId, setAssignmentVirtualKeyId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [modelSearch, setModelSearch] = useState("");
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const virtualKeysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(
    assignmentProjectId,
    { query: { enabled: assignmentScope === "virtual_key" && Boolean(assignmentProjectId) } },
  );
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const virtualKeys = virtualKeysQuery.data?.status === 200 ? virtualKeysQuery.data.data : [];
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    createAccessOptionsParams(assignmentScope, assignmentTeamId, assignmentProjectId, assignmentVirtualKeyId),
    { query: { enabled: kind === "access" && assignmentTargetReady(assignmentScope, assignmentTeamId, assignmentProjectId, assignmentVirtualKeyId) } },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? accessOptionsQuery.data.data.providers ?? [] : [];
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
  const filteredModels = models.filter((model) => {
    const term = modelSearch.trim().toLowerCase();
    if (!term) return true;
    return [model.provider_model_name, model.alias]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(term));
  });
  const visibleModelIds = filteredModels.map((model) => model.id);
  const allVisibleModelsSelected =
    visibleModelIds.length > 0 &&
    selectedModels.filter((id) => visibleModelIds.includes(id)).length === visibleModelIds.length;
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
    setDraftRules([]);
    setAssignmentScope("none");
    setAssignmentTeamId("");
    setAssignmentProjectId("");
    setAssignmentVirtualKeyId("");
    setProviderId("");
    setPoolId("");
    setSelectedModels([]);
    setModelSearch("");
  };
  const currentRuleHasLimits = Boolean(limitValue.trim());
  const currentDraftRule = (): DraftLimitRule => ({
    id: crypto.randomUUID(),
    name: draftRules.length === 0 ? "Default rule" : `Rule ${draftRules.length + 1}`,
    limitType,
    limitValue,
    intervalUnit,
    intervalCount,
  });
  const addDraftRule = () => {
    if (!currentRuleHasLimits) return;
    setDraftRules((current) => [...current, currentDraftRule()]);
    setLimitValue("");
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
  });
  const rulesForSubmit = () => {
    const rules = [...draftRules];
    if (currentRuleHasLimits) rules.push(currentDraftRule());
    return rules;
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
        if (!providerId || !poolId || selectedModels.length === 0) return;
        const response = await createAccess.mutateAsync({
          data: {
            name,
            description: description || null,
            routes: [
              {
                provider_id: providerId,
                credential_pool_id: poolId,
                model_offering_ids: selectedModels,
              },
            ],
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
    assignmentTargetReady(assignmentScope, assignmentTeamId, assignmentProjectId, assignmentVirtualKeyId) &&
    ((isLimit && (draftRules.length > 0 || currentRuleHasLimits)) ||
      (!isLimit && providerId && poolId && selectedModels.length > 0));
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
                setModelSearch("");
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
                  setModelSearch("");
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
                  setModelSearch("");
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
                  Choose the provider pool and models this policy can route to.
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
                  setSelectedModels(pool?.models?.map((model) => model.id) ?? []);
                  setModelSearch("");
                }}
                options={accessOptions.map((provider) => provider.id)}
                labels={providerOptionLabels(accessOptions)}
                placeholder={
                  accessOptionsQuery.isLoading ? "Loading providers" : "Choose provider"
                }
              />
              <SelectField
                label="Credential pool"
                value={poolId}
                onValueChange={(value) => {
                  const pool = pools.find((option) => option.id === value);
                  setPoolId(value);
                  setSelectedModels(pool?.models?.map((model) => model.id) ?? []);
                  setModelSearch("");
                }}
                options={pools.map((pool) => pool.id)}
                labels={Object.fromEntries(pools.map((pool) => [pool.id, pool.name]))}
              />
              <div className="grid gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label>Model offerings</Label>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {selectedModels.length} selected
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={visibleModelIds.length === 0}
                      onClick={() =>
                        setSelectedModels((current) =>
                          allVisibleModelsSelected
                            ? current.filter((id) => !visibleModelIds.includes(id))
                            : Array.from(new Set([...current, ...visibleModelIds])),
                        )
                      }
                    >
                      {allVisibleModelsSelected ? "Clear visible" : "Select visible"}
                    </Button>
                  </div>
                </div>
                <Input
                  value={modelSearch}
                  onChange={(event) => setModelSearch(event.target.value)}
                  placeholder="Search model offerings"
                  disabled={!poolId}
                />
                <div className="max-h-72 overflow-y-auto rounded-md border bg-background">
                  {!poolId ? (
                    <p className="p-3 text-sm text-muted-foreground">
                      Choose a provider and pool to load model offerings.
                    </p>
                  ) : filteredModels.length === 0 ? (
                    <p className="p-3 text-sm text-muted-foreground">
                      {modelSearch.trim()
                        ? "No model offerings match this search."
                        : "No model offerings are available for this pool."}
                    </p>
                  ) : (
                    filteredModels.map((model) => (
                      <label
                        key={model.id}
                        className="flex cursor-pointer items-start gap-2 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-muted/50"
                      >
                        <Checkbox
                          checked={selectedModels.includes(model.id)}
                          onCheckedChange={(checked) =>
                            setSelectedModels((current) =>
                              checked
                                ? Array.from(new Set([...current, model.id]))
                                : current.filter((id) => id !== model.id),
                            )
                          }
                        />
                        <span className="min-w-0">
                          <span className="block break-all font-mono leading-5">
                            {model.provider_model_name}
                          </span>
                          {model.alias ? (
                            <span className="block break-all text-xs text-muted-foreground">
                              {model.alias}
                            </span>
                          ) : null}
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>
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
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
                <SelectField
                  label="Interval unit"
                  value={intervalUnit}
                  onValueChange={setIntervalUnit}
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
                <Field label="Every">
                  <Input
                    type="number"
                    min={1}
                    value={intervalCount}
                    disabled={intervalUnit === "lifetime"}
                    onChange={(event) => setIntervalCount(event.target.value)}
                  />
                </Field>
              </div>
              <SelectField
                label="Limit type"
                value={limitType}
                onValueChange={setLimitType}
                options={limitTypeOptions.map((option) => option.value)}
                labels={Object.fromEntries(
                  limitTypeOptions.map((option) => [option.value, option.label]),
                )}
              />
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
  const [modelSearch, setModelSearch] = useState("");
  const [editingRoute, setEditingRoute] = useState<AccessPolicyRouteResponse | null>(null);
  const [priority, setPriority] = useState("100");
  const [weight, setWeight] = useState("100");
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    { scope_type: "org", exclude_policy_id: state?.policy.id },
    { query: { enabled: Boolean(state) } },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? accessOptionsQuery.data.data.providers ?? [] : [];
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
  const filteredModels = models.filter((model) => {
    const term = modelSearch.trim().toLowerCase();
    if (!term) return true;
    return [model.provider_model_name, model.alias]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(term));
  });
  const filteredModelIds = filteredModels.map((model) => model.id);
  const selectedVisibleModels = selectedModels.filter((id) => filteredModelIds.includes(id));
  const allVisibleModelsSelected =
    filteredModelIds.length > 0 && selectedVisibleModels.length === filteredModelIds.length;
  const createRoute = useCreateAccessPolicyRouteApiV1PoliciesAccessPolicyIdRoutesPost({
    mutation: {
      onSuccess: async () => {
        toast.success("Access route added.");
        await onChanged();
        resetForm();
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
        await onChanged();
        resetForm();
      },
      onError: () => toast.error("Access route could not be updated."),
    },
  });
  const routeModelLabels = Object.fromEntries(
    models.map((model) => [model.id, model.provider_model_name]),
  );
  const selectVisibleModels = () => {
    setSelectedModels((current) => Array.from(new Set([...current, ...filteredModelIds])));
  };
  const clearVisibleModels = () => {
    setSelectedModels((current) => current.filter((id) => !filteredModelIds.includes(id)));
  };
  const resetForm = () => {
    setProviderId("");
    setPoolId("");
    setSelectedModels([]);
    setModelSearch("");
    setEditingRoute(null);
    setPriority("100");
    setWeight("100");
  };
  const startEditRoute = (route: AccessPolicyRouteResponse) => {
    setEditingRoute(route);
    setProviderId(route.provider_id);
    setPoolId(route.credential_pool_id);
    setSelectedModels(route.model_offering_ids);
    setPriority(String(route.priority));
    setWeight(String(route.weight));
  };
  const handleDeleteRoute = async (route: AccessPolicyRouteResponse) => {
    const confirmed = await confirmPolicyImpact("Delete this access route?", () =>
      getAccessPolicyRouteImpactApiV1PoliciesAccessRoutesRouteIdImpactGet(route.id),
    );
    if (confirmed) deleteRoute.mutate({ routeId: route.id });
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
          is_active: editingRoute.is_active,
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
        is_active: true,
      },
    });
  };
  return (
    <Sheet open={Boolean(state)} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Configure access routes</SheetTitle>
          <SheetDescription>
            Routes choose a provider, one credential pool, and the model offerings this policy can serve.
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
                      <TableHead>Weight</TableHead>
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
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => startEditRoute(route)}
                          >
                            <SlidersHorizontal />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
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
                  <div className="font-medium">
                    {editingRoute ? "Edit route" : "Add route"}
                  </div>
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
                    setSelectedModels(pool?.models?.map((model) => model.id) ?? []);
                  }}
                  options={accessOptions.map((provider) => provider.id)}
                  labels={providerOptionLabels(accessOptions)}
                  placeholder="Choose provider"
                />
                <SelectField
                  label="Credential pool"
                  value={poolId}
                  onValueChange={(value) => {
                    const pool = pools.find((option) => option.id === value);
                    setPoolId(value);
                    setSelectedModels(pool?.models?.map((model) => model.id) ?? []);
                  }}
                  options={pools.map((pool) => pool.id)}
                  labels={Object.fromEntries(pools.map((pool) => [pool.id, pool.name]))}
                  placeholder="Choose pool"
                />
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <Label>Model offerings</Label>
                      <p className="text-xs text-muted-foreground">
                        Select at least one active model this route can serve.
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        {selectedModels.length} selected
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={allVisibleModelsSelected ? clearVisibleModels : selectVisibleModels}
                        disabled={!providerId || filteredModelIds.length === 0 || accessOptionsQuery.isLoading}
                      >
                        {allVisibleModelsSelected ? "Clear visible" : "Select all visible"}
                      </Button>
                    </div>
                  </div>
                  <Input
                    value={modelSearch}
                    onChange={(event) => setModelSearch(event.target.value)}
                    placeholder="Search model offerings"
                    disabled={!providerId}
                  />
                  <div className="max-h-64 overflow-y-auto rounded-md border bg-background">
                    {!providerId ? (
                      <div className="px-3 py-6 text-sm text-muted-foreground">
                        Choose a provider to load model offerings.
                      </div>
                    ) : accessOptionsQuery.isLoading ? (
                      <div className="px-3 py-6 text-sm text-muted-foreground">
                        Loading model offerings...
                      </div>
                    ) : accessOptionsQuery.isError ? (
                      <div className="px-3 py-6 text-sm text-destructive">
                        Model offerings could not be loaded.
                      </div>
                    ) : filteredModels.length === 0 ? (
                      <div className="px-3 py-6 text-sm text-muted-foreground">
                        {modelSearch.trim()
                          ? "No model offerings match this search."
                          : "No active model offerings are available for this provider."}
                      </div>
                    ) : (
                      filteredModels.map((model) => (
                        <label
                          key={model.id}
                          className="flex cursor-pointer items-start gap-2 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-muted/50"
                        >
                          <Checkbox
                            checked={selectedModels.includes(model.id)}
                            onCheckedChange={(checked) =>
                              setSelectedModels((current) =>
                                checked
                                  ? Array.from(new Set([...current, model.id]))
                                  : current.filter((id) => id !== model.id),
                              )
                            }
                          />
                          <span className="min-w-0">
                            <span className="block break-all font-mono leading-5">
                              {model.provider_model_name}
                            </span>
                            {model.alias ? (
                              <span className="block break-all text-xs text-muted-foreground">
                                {model.alias}
                              </span>
                            ) : null}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Priority">
                    <Input value={priority} onChange={(event) => setPriority(event.target.value)} />
                  </Field>
                  <Field label="Weight">
                    <Input value={weight} onChange={(event) => setWeight(event.target.value)} />
                  </Field>
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
  };
  const startEdit = (rule: LimitPolicyRuleResponse) => {
    setEditingRule(rule);
    setName(rule.name);
    setLimitType(rule.limit_type);
    setLimitValue(
      rule.limit_type === "budget_cents" ? String(rule.limit_value / 100) : String(rule.limit_value),
    );
    setIntervalUnit(rule.interval_unit);
    setIntervalCount(String(rule.interval_count));
  };
  const handleDeleteRule = async (rule: LimitPolicyRuleResponse) => {
    const confirmed = await confirmPolicyImpact(`Delete limit rule "${rule.name}"?`, () =>
      getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet(rule.id),
    );
    if (confirmed) deleteRule.mutate({ ruleId: rule.id });
  };
  const rulePayload = {
    name,
    limit_type: limitType,
    limit_value:
      limitType === "budget_cents" ? Math.round(Number(limitValue) * 100) : Number(limitValue),
    interval_unit: intervalUnit,
    interval_count: intervalUnit === "lifetime" ? 1 : Number(intervalCount || 1),
    is_active: true,
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
            Limit policies are reusable. Rules define the concrete budgets, request caps, and token caps.
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
                      <TableHead className="w-20" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(state.policy.rules ?? []).map((rule) => (
                      <TableRow key={rule.id}>
                        <TableCell className="font-medium">{rule.name}</TableCell>
                        <TableCell>{formatInterval(rule.interval_unit, rule.interval_count)}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatRuleSummary(rule)}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="icon" onClick={() => startEdit(rule)}>
                              <SlidersHorizontal />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
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
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
                  <SelectField
                    label="Interval unit"
                    value={intervalUnit}
                    onValueChange={setIntervalUnit}
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
                  <Field label="Every">
                    <Input
                      type="number"
                      min={1}
                      value={intervalCount}
                      disabled={intervalUnit === "lifetime"}
                      onChange={(event) => setIntervalCount(event.target.value)}
                    />
                  </Field>
                </div>
                <SelectField
                  label="Limit type"
                  value={limitType}
                  onValueChange={setLimitType}
                  options={limitTypeOptions.map((option) => option.value)}
                  labels={Object.fromEntries(
                    limitTypeOptions.map((option) => [option.value, option.label]),
                  )}
                />
                <Field label={limitType === "budget_cents" ? "Amount ($)" : "Value"}>
                  <Input
                    type="number"
                    min={1}
                    value={limitValue}
                    onChange={(event) => setLimitValue(event.target.value)}
                  />
                </Field>
              </div>
            </div>
          ) : null}
        </div>
        <SheetFooter>
          <Button
            onClick={submit}
            disabled={
              !name.trim() ||
              !hasAnyLimit ||
              createRule.isPending ||
              updateRule.isPending
            }
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
  const assignableTeams = canAssignOrg
    ? teams
    : teams.filter((team) => teamAdminIds.has(team.id));
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
            labels={{ org: "Organization", team: "Team", project: "Project", virtual_key: "Virtual key" }}
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
  return `${typeLabel}: ${value} ${formatInterval(rule.intervalUnit, rule.intervalCount)}`;
}

function formatRuleFilters(rule: LimitPolicyRuleResponse) {
  const filters = [
    rule.provider_id ? `Provider ${rule.provider_id.slice(0, 8)}` : null,
    rule.credential_pool_id ? `Pool ${rule.credential_pool_id.slice(0, 8)}` : null,
    rule.model_offering_id ? `Model ${rule.model_offering_id.slice(0, 8)}` : null,
    rule.access_policy_id ? `Access ${rule.access_policy_id.slice(0, 8)}` : null,
  ].filter(Boolean);
  return filters.length ? filters.join(" · ") : "All matching traffic";
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

function formatInterval(intervalUnit: string, intervalCount: string | number) {
  if (intervalUnit === "lifetime") return "over lifetime";
  const count = Number(intervalCount) || 1;
  return `every ${count} ${intervalUnit}${count === 1 ? "" : "s"}`;
}
