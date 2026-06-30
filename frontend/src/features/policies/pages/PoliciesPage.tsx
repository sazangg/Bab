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
import { useEffect, useRef, useState } from "react";
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
  getLimitPolicyImpactApiV1PoliciesLimitsPolicyIdImpactGet,
  getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet,
  useCreateAccessPolicyApiV1PoliciesAccessPost,
  useCreateLimitPolicyApiV1PoliciesLimitsPost,
  useCreateLimitPolicyRuleApiV1PoliciesLimitsPolicyIdRulesPost,
  useCreatePolicyAssignmentApiV1PoliciesAssignmentsPost,
  useDeleteAccessPolicyApiV1PoliciesAccessPolicyIdDelete,
  useDeleteLimitPolicyApiV1PoliciesLimitsPolicyIdDelete,
  useDeleteLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdDelete,
  useDeletePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdDelete,
  useGetAccessPolicyApiV1PoliciesAccessPolicyIdGet,
  useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet,
  useGetLimitPolicyApiV1PoliciesLimitsPolicyIdGet,
  useGetPolicyMetadataApiV1PoliciesMetadataGet,
  useListAccessPoliciesApiV1PoliciesAccessGet,
  useListLimitPoliciesApiV1PoliciesLimitsGet,
  useListPolicyAssignmentsApiV1PoliciesAssignmentsGet,
  useUpdateAccessPolicyApiV1PoliciesAccessPolicyIdPatch,
  useUpdateLimitPolicyApiV1PoliciesLimitsPolicyIdPatch,
  useUpdateLimitPolicyRuleApiV1PoliciesLimitsRulesRuleIdPatch,
  useUpdatePolicyAssignmentApiV1PoliciesAssignmentsAssignmentIdPatch,
} from "@/shared/api/generated/policies/policies";
import { ConfirmationDialog } from "@/features/policies/components/ConfirmationDialog";
import {
  formatLimitInterval,
  formatLimitType,
  limitRuleIntervalDefaults,
  policyMetadata,
  toLimitRuleInput,
} from "@/features/policies/lib/policy-metadata";
import { PolicySimulationPanel } from "@/features/policies/components/PolicySimulationPanel";
import { PolicySimulationResult } from "@/features/policies/components/PolicySimulationResult";
import {
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import type {
  AccessPolicyResponse,
  AccessPolicyPublicModelResponse,
  AccessPolicyRouteCandidateResponse,
  AccessPolicyProviderOption,
  AccessPolicyPublicModelInput,
  LimitPolicyResponse,
  LimitPolicyRuleResponse,
  PolicyAssignmentResponse,
  PolicyImpactResponse,
  PolicySimulationDraft,
  PolicySimulationResponse,
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
import {
  buildAccessCreateSimulationDraft,
  buildAccessEditSimulationDraft,
  buildLimitEditSimulationDraft,
  buildLimitRuleAddSimulationDraft,
  buildLimitRuleDeleteSimulationDraft,
  buildLimitRuleEditSimulationDraft,
} from "./policySimulationDraftBuilders";

type SheetKind = "access" | "limit" | null;
type LimitRulesSheetState = { policy: LimitPolicyResponse } | null;
type PolicySettingsSheetState =
  | { kind: "access"; policy: AccessPolicyResponse }
  | { kind: "limit"; policy: LimitPolicyResponse }
  | null;
type AssignmentSheetState =
  | { policyType: "access"; policyId: string; sharedPolicyId: string | null }
  | { policyType: "limit"; policyId: string; sharedPolicyId: string | null }
  | null;
type DraftLimitRule = {
  id: string;
  name: string;
  limitType: string;
  limitValue: string;
  intervalUnit: string;
  intervalCount: string;
};
type DraftAccessModel = {
  offeringId: string;
  publicModelName: string;
};
type DraftAccessRoute = {
  id: string;
  providerId: string;
  providerLabel: string;
  poolId: string;
  poolLabel: string;
  models: DraftAccessModel[];
};

function accessPolicyStatus(policy: AccessPolicyResponse, assignments: number) {
  if (!policy.is_active) return { label: "Inactive", variant: "inactive" as const };
  if (assignments === 0) return { label: "Unassigned", variant: "muted" as const };
  if (countPublicModels(policy) === 0) {
    return { label: "No routable models", variant: "expired" as const };
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
  const [limitRulesSheet, setLimitRulesSheet] = useState<LimitRulesSheetState>(null);
  const [policySettingsSheet, setPolicySettingsSheet] = useState<PolicySettingsSheetState>(null);
  const [assignmentSheet, setAssignmentSheet] = useState<AssignmentSheetState>(null);
  const [simulationDrafts, setSimulationDrafts] = useState<PolicySimulationDraft[]>([]);
  const [simulationResult, setSimulationResult] = useState<PolicySimulationResponse | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const tabParam = searchParams.get("tab");
  const activeTab = tabParam === "limits" || tabParam === "simulation" ? tabParam : "access";
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
  const assignmentCount = (policyId: string | null, type: "access" | "limit") =>
    policyId
      ? assignments.filter(
          (assignment) => assignment.policy_type === type && assignment.policy_id === policyId,
        ).length
      : 0;
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
  const currentTabIsSimulation = activeTab === "simulation";
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Policies"
        description="Access policies define public models and provider candidates. Limit policies define budgets and caps that compose across org, team, project, and key scopes."
        actions={
          <div className="flex items-center gap-2">
            {canManagePolicies && !currentTabIsSimulation ? (
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
            <TabsTrigger value="simulation">
              <Route />
              Simulation
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {currentTabIsSimulation ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <PolicySimulationPanel drafts={simulationDrafts} onResult={setSimulationResult} />
            <PolicySimulationResult result={simulationResult} />
          </div>
        ) : (
          <>
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
                  : "Reusable public model and provider candidate sets."
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
                    setAssignmentSheet({
                      policyType: "limit",
                      policyId: policy.id,
                      sharedPolicyId: policy.policy_id,
                    })
                  }
                  canManageDefinition={canManageDefinition}
                  canAssign={canAssignPolicies}
                />
              ) : (
                <AccessPoliciesTable
                  policies={filteredAccessPolicies}
                  assignmentCount={assignmentCount}
                  isLoading={accessQuery.isPending}
                  onEditPolicy={(policy) => setPolicySettingsSheet({ kind: "access", policy })}
                  onAssign={(policy) =>
                    setAssignmentSheet({
                      policyType: "access",
                      policyId: policy.id,
                      sharedPolicyId: policy.policy_id,
                    })
                  }
                  canManageDefinition={canManageDefinition}
                  canAssign={canAssignPolicies}
                />
              )}
            </PolicyCard>
          </>
        )}
      </div>

      <CreatePolicySheet
        kind={sheetKind}
        onOpenChange={(open) => !open && setSheetKind(null)}
        onCreated={async () => {
          setSheetKind(null);
          await invalidatePolicies();
        }}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setSearchParams({ tab: "simulation" });
          setSheetKind(null);
        }}
      />
      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
        onChanged={invalidatePolicies}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setSearchParams({ tab: "simulation" });
          setLimitRulesSheet(null);
        }}
      />
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setSearchParams({ tab: "simulation" });
          setPolicySettingsSheet(null);
        }}
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
  const [policySettingsSheet, setPolicySettingsSheet] = useState<PolicySettingsSheetState>(null);
  const [assignmentSheet, setAssignmentSheet] = useState<AssignmentSheetState>(null);
  const [simulationDrafts, setSimulationDrafts] = useState<PolicySimulationDraft[]>([]);
  const [simulationResult, setSimulationResult] = useState<PolicySimulationResponse | null>(null);
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
      ? assignmentsQuery.data.data.filter((assignment) => assignment.policy_id === policy?.policy_id)
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

  const publicModelCount = countPublicModels(policy);
  const candidateCount = countPublicModelCandidates(policy);
  const canManageDefinition = canManagePolicyDefinition(currentUser, policy);
  return (
    <>
      <PolicyDetailLayout
        title={policy.name}
        description={policy.description || "Access policy public model configuration."}
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
                onClick={() =>
                  setAssignmentSheet({
                    policyType: "access",
                    policyId,
                    sharedPolicyId: policy.policy_id,
                  })
                }
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
          </div>
        }
        metrics={[
          { label: "Public models", value: publicModelCount },
          { label: "Candidates", value: candidateCount },
          { label: "Assignments", value: assignments.length },
          { label: "Status", value: policy.is_active ? "Active" : "Inactive" },
        ]}
        detailTitle="Public models"
        detailDescription="Public models are the client-facing names and fallback order for this policy."
        detailIcon={Route}
        detailContent={<AccessPublicModelsDetailTable publicModels={policy.public_models ?? []} />}
        assignments={assignments}
        onChanged={invalidatePolicies}
        canManageAssignments={canAssignPolicies}
      />
      {simulationDrafts.length > 0 ? (
        <PolicySimulationPreviewSection
          drafts={simulationDrafts}
          result={simulationResult}
          onResult={setSimulationResult}
        />
      ) : null}
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setPolicySettingsSheet(null);
        }}
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
  const [simulationDrafts, setSimulationDrafts] = useState<PolicySimulationDraft[]>([]);
  const [simulationResult, setSimulationResult] = useState<PolicySimulationResponse | null>(null);
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
      ? assignmentsQuery.data.data.filter((assignment) => assignment.policy_id === policy?.policy_id)
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
                onClick={() =>
                  setAssignmentSheet({
                    policyType: "limit",
                    policyId,
                    sharedPolicyId: policy.policy_id,
                  })
                }
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
      {simulationDrafts.length > 0 ? (
        <PolicySimulationPreviewSection
          drafts={simulationDrafts}
          result={simulationResult}
          onResult={setSimulationResult}
        />
      ) : null}
      <LimitRulesSheet
        state={limitRulesSheet}
        onOpenChange={(open) => !open && setLimitRulesSheet(null)}
        onChanged={invalidatePolicies}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setLimitRulesSheet(null);
        }}
      />
      <PolicySettingsSheet
        state={policySettingsSheet}
        onOpenChange={(open) => !open && setPolicySettingsSheet(null)}
        onChanged={invalidatePolicies}
        onPreview={(drafts) => {
          setSimulationDrafts(drafts);
          setSimulationResult(null);
          setPolicySettingsSheet(null);
        }}
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

function PolicySimulationPreviewSection({
  drafts,
  result,
  onResult,
}: {
  drafts: PolicySimulationDraft[];
  result: PolicySimulationResponse | null;
  onResult: (result: PolicySimulationResponse | null) => void;
}) {
  return (
    <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
      <div className="xl:col-span-2">
        <h2 className="text-base font-semibold">Simulation preview</h2>
      </div>
      <PolicySimulationPanel drafts={drafts} onResult={onResult} />
      <PolicySimulationResult result={result} />
    </section>
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

function AccessPublicModelsDetailTable({
  publicModels,
}: {
  publicModels: AccessPolicyPublicModelResponse[];
}) {
  const columns: DataTableColumn<AccessPolicyPublicModelResponse>[] = [
    {
      key: "name",
      header: "Public model",
      className: "font-medium",
      cell: (publicModel) => publicModel.public_model_name,
    },
    {
      key: "routing",
      header: "Routing",
      cell: (publicModel) => (
        <>
          {formatRoutingMode(publicModel.routing_mode)}
          {publicModel.fallback_on.length ? (
            <div className="text-xs text-muted-foreground">
              {publicModel.fallback_on.map(formatFallbackReason).join(", ")}
            </div>
          ) : null}
        </>
      ),
    },
    {
      key: "candidates",
      header: "Candidates",
      cell: (publicModel) => {
        const activeCandidates = (publicModel.candidates ?? []).filter(
          (candidate) => candidate.is_active,
        );
        const orderedCandidates = [...(publicModel.candidates ?? [])].sort(
          (left, right) => left.priority - right.priority || right.weight - left.weight,
        );
        return (
          <div className="grid gap-1">
            <div>
              {activeCandidates.length} active{" "}
              <span className="text-xs text-muted-foreground">
                / {(publicModel.candidates ?? []).length} configured
              </span>
            </div>
            <div className="grid gap-0.5 text-xs text-muted-foreground">
              {orderedCandidates.slice(0, 3).map((candidate) => (
                <span
                  key={`${candidate.provider_id}:${candidate.credential_pool_id}:${candidate.model_offering_id}`}
                  className="truncate"
                >
                  #{candidate.priority} model {candidate.model_offering_id.slice(0, 8)}
                </span>
              ))}
              {orderedCandidates.length > 3 ? (
                <span>+{orderedCandidates.length - 3} more</span>
              ) : null}
            </div>
          </div>
        );
      },
    },
    {
      key: "status",
      header: "Status",
      cell: (publicModel) => (
        <StatusBadge variant={publicModel.is_active ? "active" : "inactive"}>
          {publicModel.is_active ? "Active" : "Inactive"}
        </StatusBadge>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      data={publicModels}
      getRowKey={(publicModel) => publicModel.id}
      empty={{
        title: "No public models configured",
        description: "Add at least one public model before assigning this policy.",
      }}
    />
  );
}

function LimitRulesDetailTable({ rules }: { rules: LimitPolicyRuleResponse[] }) {
  const columns: DataTableColumn<LimitPolicyRuleResponse>[] = [
    { key: "rule", header: "Rule", className: "font-medium", cell: (rule) => rule.name },
    {
      key: "interval",
      header: "Interval",
      cell: (rule) => formatLimitInterval(rule.interval_unit, rule.interval_count),
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
      cell: () => "All matching traffic",
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
  onEditPolicy,
  onAssign,
  canManageDefinition,
  canAssign,
}: {
  policies: AccessPolicyResponse[];
  assignmentCount: (policyId: string | null, type: "access") => number;
  isLoading: boolean;
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
      key: "public-models",
      header: "Models",
      cell: (policy) => (
        <>
          <div>{countPublicModels(policy)} public models</div>
          <div className="text-xs text-muted-foreground">
            {countPublicModelCandidates(policy)} candidates
          </div>
        </>
      ),
    },
    {
      key: "assignments",
      header: "Assignments",
      cell: (policy) => assignmentCount(policy.policy_id, "access"),
    },
    {
      key: "status",
      header: "Status",
      cell: (policy) => {
        const status = accessPolicyStatus(policy, assignmentCount(policy.policy_id, "access"));
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
        empty={{ title: "No access policies", description: "Create an access policy first." }}
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
  assignmentCount: (policyId: string | null, type: "limit") => number;
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
      cell: (policy) => assignmentCount(policy.policy_id, "limit"),
    },
    {
      key: "status",
      header: "Status",
      cell: (policy) => {
        const status = limitPolicyStatus(policy, assignmentCount(policy.policy_id, "limit"));
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
  onPreview,
}: {
  state: PolicySettingsSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
  onPreview?: (drafts: PolicySimulationDraft[]) => void;
}) {
  return (
    <Sheet open={Boolean(state)} onOpenChange={onOpenChange}>
      {state ? (
        <PolicySettingsSheetContent
          key={`${state.kind}:${state.policy.id}`}
          state={state}
          onOpenChange={onOpenChange}
          onChanged={onChanged}
          onPreview={onPreview}
        />
      ) : null}
    </Sheet>
  );
}

function PolicySettingsSheetContent({
  state,
  onOpenChange,
  onChanged,
  onPreview,
}: {
  state: NonNullable<PolicySettingsSheetState>;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
  onPreview?: (drafts: PolicySimulationDraft[]) => void;
}) {
  const [name, setName] = useState(state.policy.name);
  const [description, setDescription] = useState(state.policy.description ?? "");
  const [isActive, setIsActive] = useState(state.policy.is_active);
  const [publicModels, setPublicModels] = useState<AccessPolicyPublicModelInput[]>(
    state.kind === "access"
      ? (state.policy.public_models ?? []).map(publicModelResponseToInput)
      : [],
  );
  const [publicModelName, setPublicModelName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const accessOptionsQuery = useGetAccessPolicyOptionsApiV1PoliciesAccessOptionsGet(
    state.kind === "access"
      ? createAccessOptionsParams(
          state.policy.owning_scope_type ?? "none",
          state.policy.owning_team_id ?? "",
          state.policy.owning_project_id ?? "",
          state.policy.owning_virtual_key_id ?? "",
        )
      : createAccessOptionsParams("none", "", "", ""),
    { query: { enabled: state.kind === "access" } },
  );
  const accessOptions =
    accessOptionsQuery.data?.status === 200 ? (accessOptionsQuery.data.data.providers ?? []) : [];
  const pools = accessOptions.find((provider) => provider.id === providerId)?.pools ?? [];
  const models = pools.find((pool) => pool.id === poolId)?.models ?? [];
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
      ...(state.kind === "access" ? { public_models: publicModels } : {}),
    };
    if (state.kind === "access") {
      updateAccessPolicy.mutate({ policyId: state.policy.id, data });
      return;
    }
    updateLimitPolicy.mutate({ policyId: state.policy.id, data });
  };
  const preview = () => {
    if (!onPreview) return;
    if (!name.trim()) return;
    if (state.kind === "access") {
      if (publicModels.length === 0) return;
      onPreview([
        buildAccessEditSimulationDraft(state.policy, {
          name,
          description,
          isActive,
          publicModels,
        }),
      ]);
      return;
    }
    onPreview([
      buildLimitEditSimulationDraft(state.policy, {
        name,
        description,
        isActive,
      }),
    ]);
  };
  const actionDisabled =
    !name.trim() ||
    (state.kind === "access" && publicModels.length === 0) ||
    updateAccessPolicy.isPending ||
    updateLimitPolicy.isPending;

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
        {state.kind === "access" ? (
          <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
            <div>
              <div className="text-sm font-medium">Public models</div>
              <p className="text-xs text-muted-foreground">
                Public model names are the client-facing model IDs. Candidate order controls
                fallback priority.
              </p>
            </div>
            <EditablePublicModelsList
              publicModels={publicModels}
              onChange={setPublicModels}
            />
            <Field label="Public model name">
              <Input
                value={publicModelName}
                onChange={(event) => setPublicModelName(event.target.value)}
                placeholder="Defaults to selected model name"
              />
            </Field>
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
              onClick={() => {
                const selectedOfferings = models.filter((model) => selectedModels.includes(model.id));
                if (!providerId || !poolId || selectedOfferings.length === 0) return;
                setPublicModels((current) =>
                  addCandidatesToPublicModels({
                    publicModels: current,
                    publicModelName,
                    providerId,
                    poolId,
                    models: selectedOfferings.map((model) => ({
                      offeringId: model.id,
                      publicModelName: model.provider_model_name,
                    })),
                  }),
                );
                setPublicModelName("");
                setSelectedModels([]);
              }}
              disabled={!providerId || !poolId || selectedModels.length === 0}
            >
              <Plus />
              Add candidates
            </Button>
          </div>
        ) : null}
      </div>
      <SheetFooter>
        {onPreview ? (
          <Button type="button" variant="outline" onClick={preview} disabled={actionDisabled}>
            <Route />
            Preview
          </Button>
        ) : null}
        <Button
          onClick={submit}
          disabled={actionDisabled}
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

function EditablePublicModelsList({
  publicModels,
  onChange,
}: {
  publicModels: AccessPolicyPublicModelInput[];
  onChange: (publicModels: AccessPolicyPublicModelInput[]) => void;
}) {
  if (publicModels.length === 0) {
    return (
      <div className="rounded-md border border-dashed bg-background px-3 py-4 text-sm text-muted-foreground">
        No public models configured.
      </div>
    );
  }
  return (
    <div className="grid gap-2">
      {publicModels.map((publicModel) => (
        <div key={publicModel.public_model_name} className="rounded-md border bg-background p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{publicModel.public_model_name}</div>
              <div className="text-xs text-muted-foreground">
                {formatRoutingMode(publicModel.routing_mode ?? "single_route")} ·{" "}
                {publicModel.candidates.length}{" "}
                candidate{publicModel.candidates.length === 1 ? "" : "s"}
              </div>
            </div>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label="Remove public model"
              onClick={() =>
                onChange(
                  publicModels.filter(
                    (candidate) =>
                      candidate.public_model_name !== publicModel.public_model_name,
                  ),
                )
              }
            >
              <Trash2 />
            </Button>
          </div>
          <div className="mt-2 grid gap-1">
            {publicModel.candidates.map((candidate) => (
              <div
                key={`${candidate.provider_id}:${candidate.credential_pool_id}:${candidate.model_offering_id}`}
                className="flex items-center justify-between gap-2 rounded bg-muted/40 px-2 py-1 text-xs"
              >
                <span className="min-w-0 truncate">
                  Priority {candidate.priority} · model {String(candidate.model_offering_id).slice(0, 8)}
                </span>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="Remove candidate"
                  onClick={() =>
                    onChange(
                      publicModels
                        .map((item) =>
                          item.public_model_name === publicModel.public_model_name
                            ? {
                                ...item,
                                candidates: item.candidates.filter(
                                  (existing) =>
                                    existing.model_offering_id !== candidate.model_offering_id ||
                                    existing.provider_id !== candidate.provider_id ||
                                    existing.credential_pool_id !== candidate.credential_pool_id,
                                ),
                              }
                            : item,
                        )
                        .filter((item) => item.candidates.length > 0),
                    )
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CreatePolicySheet({
  kind,
  onOpenChange,
  onCreated,
  onPreview,
}: {
  kind: SheetKind;
  onOpenChange: (open: boolean) => void;
  onCreated: () => Promise<void>;
  onPreview: (drafts: PolicySimulationDraft[]) => void;
}) {
  const metadataQuery = useGetPolicyMetadataApiV1PoliciesMetadataGet();
  const metadataResponse =
    metadataQuery.data?.status === 200 ? metadataQuery.data.data : undefined;
  const intervalDefaults = limitRuleIntervalDefaults(metadataResponse);
  const wasOpenRef = useRef(false);
  const intervalTouchedRef = useRef(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [limitType, setLimitType] = useState("requests");
  const [limitValue, setLimitValue] = useState("");
  const [intervalUnit, setIntervalUnit] = useState(() => limitRuleIntervalDefaults().intervalUnit);
  const [intervalCount, setIntervalCount] = useState(
    () => limitRuleIntervalDefaults().intervalCount,
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
    intervalTouchedRef.current = false;
    setName("");
    setDescription("");
    setLimitType("requests");
    setLimitValue("");
    setIntervalUnit(intervalDefaults.intervalUnit);
    setIntervalCount(intervalDefaults.intervalCount);
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
  useEffect(() => {
    const isOpen = Boolean(kind);
    if (isOpen && !wasOpenRef.current) {
      intervalTouchedRef.current = false;
      setIntervalUnit(intervalDefaults.intervalUnit);
      setIntervalCount(intervalDefaults.intervalCount);
    }
    wasOpenRef.current = isOpen;
  }, [intervalDefaults.intervalCount, intervalDefaults.intervalUnit, kind]);
  useEffect(() => {
    if (kind !== "limit" || !metadataResponse || intervalTouchedRef.current) return;
    setIntervalUnit(intervalDefaults.intervalUnit);
    setIntervalCount(intervalDefaults.intervalCount);
  }, [intervalDefaults.intervalCount, intervalDefaults.intervalUnit, kind, metadataResponse]);
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
  const ruleInput = (rule: DraftLimitRule) => toLimitRuleInput(rule);
  const rulesForSubmit = () => {
    const rules = [...draftRules];
    if (currentRuleHasLimits) rules.push(currentDraftRule());
    return rules;
  };
  const currentAccessRoute = (): DraftAccessRoute | null => {
    const provider = accessOptions.find((option) => option.id === providerId);
    const pool = pools.find((option) => option.id === poolId);
    const routeModels = models
      .filter((model) => selectedModels.includes(model.id))
      .map((model) => ({
        offeringId: model.id,
        publicModelName: model.provider_model_name,
      }));
    if (!provider || !pool || routeModels.length === 0) return null;
    return {
      id: crypto.randomUUID(),
      providerId,
      providerLabel: provider.display_name,
      poolId,
      poolLabel: pool.name,
      models: routeModels,
    };
  };
  const accessRoutesForSubmit = () => {
    const currentRoute = currentAccessRoute();
    return currentRoute ? [...draftRoutes, currentRoute] : draftRoutes;
  };
  const assignmentPayload = (sharedPolicyId: string | null) => {
    if (!sharedPolicyId) return null;
    if (assignmentScope === "none") return null;
    return {
      policy_id: sharedPolicyId,
      policy_type: isLimit ? "limit" : "access",
      scope_type: assignmentScope,
      team_id: assignmentScope === "team" ? assignmentTeamId : null,
      project_id: assignmentScope === "project" ? assignmentProjectId : null,
      virtual_key_id: assignmentScope === "virtual_key" ? assignmentVirtualKeyId : null,
      is_active: true,
    };
  };
  const simulationDraft = (): PolicySimulationDraft | null => {
    if (!name.trim()) return null;
    if (isLimit) {
      const rules = rulesForSubmit();
      if (rules.length === 0) return null;
      return {
        kind: "limit",
        operation: "add_policy",
        assignment: simulationDraftAssignment(
          assignmentScope,
          assignmentTeamId,
          assignmentProjectId,
          assignmentVirtualKeyId,
        ),
        limit_policy: {
          name: name.trim(),
          description: description.trim() || null,
          rules: rules.map(ruleInput),
          is_active: true,
        },
      };
    }
    const routes = accessRoutesForSubmit();
    if (routes.length === 0) return null;
    return buildAccessCreateSimulationDraft({
      name,
      description,
      publicModels: routes.flatMap(toPublicModelInputs),
      assignment: simulationDraftAssignment(
        assignmentScope,
        assignmentTeamId,
        assignmentProjectId,
        assignmentVirtualKeyId,
      ),
    });
  };
  const preview = () => {
    const draft = simulationDraft();
    if (!draft) return;
    onPreview([draft]);
  };
  const submit = async () => {
    if (!name.trim()) return;
    try {
      let sharedPolicyId: string | null = null;
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
        sharedPolicyId = response.data.policy_id;
      } else {
        const routes = accessRoutesForSubmit();
        if (routes.length === 0) return;
        const response = await createAccess.mutateAsync({
          data: {
            name,
            description: description || null,
            public_models: routes.flatMap(toPublicModelInputs),
          },
        });
        if (response.status !== 201) return;
        sharedPolicyId = response.data.policy_id;
      }
      const payload = assignmentPayload(sharedPolicyId);
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
              : "Create initial public models and optionally assign the policy immediately."}
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
                <div className="text-sm font-medium">Initial public models</div>
                <p className="text-xs text-muted-foreground">
                  Add provider model candidates. The provider model name becomes the public model
                  name by default.
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
                          {route.models.length} public model
                          {route.models.length === 1 ? "" : "s"}
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
                Add candidates
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
                onIntervalUnitChange={(value) => {
                  intervalTouchedRef.current = true;
                  setIntervalUnit(value);
                }}
                intervalCount={intervalCount}
                onIntervalCountChange={(value) => {
                  intervalTouchedRef.current = true;
                  setIntervalCount(value);
                }}
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
          <Button type="button" variant="outline" onClick={preview} disabled={!canSubmit}>
            <Route />
            Preview in simulation
          </Button>
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

export function LimitRulesSheet({
  state,
  onOpenChange,
  onChanged,
  onPreview,
}: {
  state: LimitRulesSheetState;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
  onPreview?: (drafts: PolicySimulationDraft[]) => void;
}) {
  const metadataQuery = useGetPolicyMetadataApiV1PoliciesMetadataGet();
  const metadataResponse =
    metadataQuery.data?.status === 200 ? metadataQuery.data.data : undefined;
  const intervalDefaults = limitRuleIntervalDefaults(metadataResponse);
  const wasOpenRef = useRef(false);
  const intervalTouchedRef = useRef(false);
  const [editingRule, setEditingRule] = useState<LimitPolicyRuleResponse | null>(null);
  const [name, setName] = useState("Rule");
  const [limitType, setLimitType] = useState("requests");
  const [limitValue, setLimitValue] = useState("");
  const [intervalUnit, setIntervalUnit] = useState(() => limitRuleIntervalDefaults().intervalUnit);
  const [intervalCount, setIntervalCount] = useState(
    () => limitRuleIntervalDefaults().intervalCount,
  );
  const [ruleIsActive, setRuleIsActive] = useState(true);
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
    intervalTouchedRef.current = false;
    setEditingRule(null);
    setName("Rule");
    setLimitType("requests");
    setLimitValue("");
    setIntervalUnit(intervalDefaults.intervalUnit);
    setIntervalCount(intervalDefaults.intervalCount);
    setRuleIsActive(true);
  };
  useEffect(() => {
    const isOpen = Boolean(state);
    if (isOpen && !wasOpenRef.current && !editingRule) {
      intervalTouchedRef.current = false;
      setIntervalUnit(intervalDefaults.intervalUnit);
      setIntervalCount(intervalDefaults.intervalCount);
    }
    wasOpenRef.current = isOpen;
  }, [editingRule, intervalDefaults.intervalCount, intervalDefaults.intervalUnit, state]);
  useEffect(() => {
    if (!state || editingRule || !metadataResponse || intervalTouchedRef.current) return;
    setIntervalUnit(intervalDefaults.intervalUnit);
    setIntervalCount(intervalDefaults.intervalCount);
  }, [
    editingRule,
    intervalDefaults.intervalCount,
    intervalDefaults.intervalUnit,
    metadataResponse,
    state,
  ]);
  const startEdit = (rule: LimitPolicyRuleResponse) => {
    intervalTouchedRef.current = true;
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
  };
  const handleDeleteRule = async (rule: LimitPolicyRuleResponse) => {
    await requestImpactConfirmation(
      `Delete limit rule "${rule.name}"?`,
      () => getLimitPolicyRuleImpactApiV1PoliciesLimitsRulesRuleIdImpactGet(rule.id),
      () => deleteRule.mutate({ ruleId: rule.id }),
    );
  };
  const rulePayload = toLimitRuleInput(
    { name, limitType, limitValue, intervalUnit, intervalCount },
    ruleIsActive,
  );
  const hasAnyLimit = Boolean(limitValue.trim());
  const submit = () => {
    if (!state || !name.trim() || !hasAnyLimit) return;
    if (editingRule) {
      updateRule.mutate({ ruleId: editingRule.id, data: rulePayload });
      return;
    }
    createRule.mutate({ policyId: state.policy.id, data: rulePayload });
  };
  const previewCurrentRule = () => {
    if (!state || !onPreview || !name.trim() || !hasAnyLimit) return;
    onPreview([
      editingRule
        ? buildLimitRuleEditSimulationDraft(state.policy, editingRule.id, rulePayload)
        : buildLimitRuleAddSimulationDraft(state.policy, rulePayload),
    ]);
  };
  const previewDeleteRule = (rule: LimitPolicyRuleResponse) => {
    if (!state || !onPreview) return;
    onPreview([buildLimitRuleDeleteSimulationDraft(state.policy, rule.id)]);
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
                          {formatLimitInterval(rule.interval_unit, rule.interval_count)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatRuleSummary(rule)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          All matching traffic
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
                            {onPreview ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Preview delete ${rule.name}`}
                                onClick={() => previewDeleteRule(rule)}
                              >
                                <Route />
                              </Button>
                            ) : null}
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
                  onIntervalUnitChange={(value) => {
                    intervalTouchedRef.current = true;
                    setIntervalUnit(value);
                  }}
                  intervalCount={intervalCount}
                  onIntervalCountChange={(value) => {
                    intervalTouchedRef.current = true;
                    setIntervalCount(value);
                  }}
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
          {onPreview ? (
            <Button
              type="button"
              variant="outline"
              onClick={previewCurrentRule}
              disabled={!name.trim() || !hasAnyLimit}
            >
              <Route />
              Preview
            </Button>
          ) : null}
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
    if (!state.sharedPolicyId) return;
    if (scopeType !== "org" && !scopeId.trim()) return;
    createAssignment.mutate({
      data: {
        policy_id: state.sharedPolicyId,
        policy_type: state.policyType,
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
}: {
  limitType: string;
  onLimitTypeChange: (value: string) => void;
  limitValue: string;
  onLimitValueChange: (value: string) => void;
  intervalUnit: string;
  onIntervalUnitChange: (value: string) => void;
  intervalCount: string;
  onIntervalCountChange: (value: string) => void;
}) {
  const metadataQuery = useGetPolicyMetadataApiV1PoliciesMetadataGet();
  const metadata = policyMetadata(
    metadataQuery.data?.status === 200 ? metadataQuery.data.data : undefined,
  );
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
          options={metadata.intervalUnits}
          labels={metadata.intervalUnitLabels}
        />
      </div>
      <SelectField
        label="Limit type"
        value={limitType}
        onValueChange={onLimitTypeChange}
        options={metadata.limitTypes}
        labels={metadata.limitTypeLabels}
      />
      <Field label={limitType === "budget_cents" ? "Amount ($)" : "Value"}>
        <Input
          type="number"
          min={1}
          value={limitValue}
          onChange={(event) => onLimitValueChange(event.target.value)}
        />
      </Field>
    </>
  );
}

function formatRuleSummary(rule: LimitPolicyRuleResponse) {
  const typeLabel = formatLimitType(rule.limit_type);
  const value =
    rule.limit_type === "budget_cents"
      ? `$${(rule.limit_value / 100).toLocaleString()}`
      : rule.limit_value.toLocaleString();
  return `${typeLabel}: ${value}`;
}

function formatDraftRuleSummary(rule: DraftLimitRule) {
  const typeLabel = formatLimitType(rule.limitType);
  const value =
    rule.limitType === "budget_cents"
      ? `$${Number(rule.limitValue).toLocaleString()}`
      : Number(rule.limitValue).toLocaleString();
  return `${typeLabel}: ${value} ${formatLimitInterval(rule.intervalUnit, rule.intervalCount)}`;
}

function toPublicModelInputs(route: DraftAccessRoute): AccessPolicyPublicModelInput[] {
  return route.models.map((model, index) => ({
    public_model_name: model.publicModelName,
    routing_mode: "single_route",
    fallback_on: [],
    max_route_attempts: 1,
    is_active: true,
    candidates: [
      {
        provider_id: route.providerId,
        credential_pool_id: route.poolId,
        model_offering_id: model.offeringId,
        priority: index + 1,
        weight: 1,
        is_active: true,
      },
    ],
  }));
}

function publicModelResponseToInput(
  publicModel: AccessPolicyPublicModelResponse,
): AccessPolicyPublicModelInput {
  return {
    public_model_name: publicModel.public_model_name,
    routing_mode: publicModel.routing_mode,
    fallback_on: publicModel.fallback_on,
    max_route_attempts: publicModel.max_route_attempts,
    is_active: publicModel.is_active,
    candidates: (publicModel.candidates ?? []).map(candidateResponseToInput),
  };
}

function candidateResponseToInput(candidate: AccessPolicyRouteCandidateResponse) {
  return {
    provider_id: candidate.provider_id,
    credential_pool_id: candidate.credential_pool_id,
    model_offering_id: candidate.model_offering_id,
    priority: candidate.priority,
    weight: candidate.weight,
    is_active: candidate.is_active,
  };
}

function addCandidatesToPublicModels({
  publicModels,
  publicModelName,
  providerId,
  poolId,
  models,
}: {
  publicModels: AccessPolicyPublicModelInput[];
  publicModelName: string;
  providerId: string;
  poolId: string;
  models: DraftAccessModel[];
}) {
  const explicitName = publicModelName.trim();
  const next = [...publicModels];
  for (const model of models) {
    const name = explicitName || model.publicModelName;
    const existingIndex = next.findIndex((item) => item.public_model_name === name);
    const existing = existingIndex >= 0 ? next[existingIndex] : null;
    const priority = (existing?.candidates.length ?? 0) + 1;
    const candidate = {
      provider_id: providerId,
      credential_pool_id: poolId,
      model_offering_id: model.offeringId,
      priority,
      weight: 1,
      is_active: true,
    };
    if (existing) {
      const isDuplicate = existing.candidates.some(
        (item) =>
          item.provider_id === candidate.provider_id &&
          item.credential_pool_id === candidate.credential_pool_id &&
          item.model_offering_id === candidate.model_offering_id,
      );
      if (!isDuplicate) {
        next[existingIndex] = {
          ...existing,
          routing_mode: "ordered_fallback",
          fallback_on: existing.fallback_on?.length ? existing.fallback_on : ["provider_5xx"],
          max_route_attempts: Math.max(existing.max_route_attempts ?? 1, priority),
          candidates: [...existing.candidates, candidate],
        };
      }
      continue;
    }
    next.push({
      public_model_name: name,
      routing_mode: "single_route",
      fallback_on: [],
      max_route_attempts: 1,
      is_active: true,
      candidates: [candidate],
    });
  }
  return next;
}

function countPublicModels(policy: AccessPolicyResponse) {
  return (policy.public_models ?? []).length;
}

function countPublicModelCandidates(policy: AccessPolicyResponse) {
  return (policy.public_models ?? []).reduce(
    (total, publicModel) => total + (publicModel.candidates ?? []).length,
    0,
  );
}

function formatRoutingMode(value: string) {
  if (value === "ordered_fallback") return "Ordered fallback";
  if (value === "single_route") return "Single route";
  return value.replaceAll("_", " ");
}

function formatFallbackReason(value: string) {
  if (value === "provider_5xx") return "5xx";
  return value.replaceAll("_", " ");
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

function simulationDraftAssignment(
  scopeType: string,
  teamId: string,
  projectId: string,
  virtualKeyId: string,
): PolicySimulationDraft["assignment"] {
  if (scopeType === "none") return null;
  return {
    scope_type: scopeType as NonNullable<PolicySimulationDraft["assignment"]>["scope_type"],
    team_id: scopeType === "team" ? teamId : null,
    project_id: scopeType === "project" ? projectId : null,
    virtual_key_id: scopeType === "virtual_key" ? virtualKeyId : null,
  };
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
