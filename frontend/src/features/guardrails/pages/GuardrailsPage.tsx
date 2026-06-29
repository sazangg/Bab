import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Shield, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  getAssignmentImpactApiV1GuardrailsAssignmentsAssignmentIdImpactGet,
  getPolicyImpactApiV1GuardrailsPoliciesPolicyIdImpactGet,
  useCreateAssignmentApiV1GuardrailsAssignmentsPost,
  useCreatePolicyApiV1GuardrailsPoliciesPost,
  useDeleteAssignmentApiV1GuardrailsAssignmentsAssignmentIdDelete,
  useDeletePolicyApiV1GuardrailsPoliciesPolicyIdDelete,
  useListAssignmentsApiV1GuardrailsAssignmentsGet,
  useListEventsApiV1GuardrailsEventsGet,
  useListPoliciesApiV1GuardrailsPoliciesGet,
  useUpdateAssignmentApiV1GuardrailsAssignmentsAssignmentIdPatch,
  useUpdatePolicyApiV1GuardrailsPoliciesPolicyIdPatch,
} from "@/shared/api/generated/guardrails/guardrails";
import {
  listVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useListProjectsApiV1ProjectsGet,
} from "@/shared/api/generated/projects/projects";
import type {
  GuardrailAssignmentResponse,
  GuardrailPolicyResponse,
  GuardrailRuleInput,
  PolicySimulationDraft,
  PolicySimulationResponse,
} from "@/shared/api/generated/schemas";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { httpClient } from "@/shared/api/http-client";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatCard } from "@/shared/components/StatCard";

import { GuardrailAssignmentSheet } from "../components/GuardrailAssignmentSheet";
import { GuardrailPolicySheet } from "../components/GuardrailPolicySheet";
import { useGuardrailImpactConfirmation } from "../components/GuardrailImpactDialog";
import { GuardrailAssignmentsTab } from "../sections/GuardrailAssignmentsTab";
import { GuardrailEventsTab } from "../sections/GuardrailEventsTab";
import { GuardrailPoliciesTab } from "../sections/GuardrailPoliciesTab";
import { GuardrailSimulationTab } from "../sections/GuardrailSimulationTab";
import {
  buildRuleConfig,
  buildScopeLabels,
  buildScopeOptions,
  emptyAssignmentForm,
  emptyPolicyForm,
  firstAssignableScope,
  newMatcherForm,
  newRuleForm,
  normalizeRulePhase,
  parseRuleValues,
  parseMatcherValue,
  readRuleDetector,
  validateRuleForm,
  type AssignmentFormState,
  type GuardrailPolicyOption,
  type PolicyFormState,
  type ScopeType,
} from "../lib/guardrail-helpers";

const TAB_VALUES = ["policies", "assignments", "simulation", "events"] as const;
type GuardrailTab = (typeof TAB_VALUES)[number];

export function GuardrailsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [policySheetOpen, setPolicySheetOpen] = useState(false);
  const [assignmentSheetOpen, setAssignmentSheetOpen] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<GuardrailPolicyResponse | null>(null);
  const [editingAssignment, setEditingAssignment] = useState<GuardrailAssignmentResponse | null>(
    null,
  );
  const [policyForm, setPolicyForm] = useState<PolicyFormState>(emptyPolicyForm);
  const [assignmentForm, setAssignmentForm] = useState<AssignmentFormState>(emptyAssignmentForm);
  const [simulationDrafts, setSimulationDrafts] = useState<PolicySimulationDraft[]>([]);
  const [policySimulationResult, setPolicySimulationResult] =
    useState<PolicySimulationResponse | null>(null);
  const { confirmWithImpact, dialog: impactDialog } = useGuardrailImpactConfirmation();

  const requestedTab = searchParams.get("tab");
  const activeTab: GuardrailTab = TAB_VALUES.includes(requestedTab as GuardrailTab)
    ? (requestedTab as GuardrailTab)
    : "policies";

  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageGuardrails = hasPermission(currentUser, "guardrails.manage");
  const canAssignGuardrails =
    canManageGuardrails ||
    hasAnyTeamAdminMembership(currentUser) ||
    hasAnyProjectAdminMembership(currentUser);

  const policiesQuery = useListPoliciesApiV1GuardrailsPoliciesGet();
  const policyOptionsQuery = useQuery({
    queryKey: ["guardrail-policy-options"],
    queryFn: async () => {
      const response = await httpClient.get<GuardrailPolicyOption[]>(
        "/api/v1/guardrails/policy-options",
      );
      return response.data;
    },
    enabled: Boolean(currentUser),
  });
  const assignmentsQuery = useListAssignmentsApiV1GuardrailsAssignmentsGet();
  const recentBlocksQuery = useListEventsApiV1GuardrailsEventsGet({
    decision: "blocked",
    limit: 50,
  });
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const policies = policiesQuery.data?.status === 200 ? policiesQuery.data.data : [];
  const policyOptions = policyOptionsQuery.data ?? [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const recentBlockCount =
    recentBlocksQuery.data?.status === 200 ? recentBlocksQuery.data.data.items.length : 0;

  const virtualKeyQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: ["guardrail-assignment-virtual-keys", project.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        listVirtualKeysApiV1ProjectsProjectIdKeysGet(project.id, { signal }),
      enabled: projects.length > 0,
    })),
  });
  const virtualKeys = virtualKeyQueries.flatMap((query, index) => {
    const project = projects[index];
    if (query.data?.status !== 200 || !project) return [];
    return query.data.data.map((key) => ({ ...key, project_name: project.name }));
  });
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
  const assignableTeams = canManageGuardrails
    ? teams
    : teams.filter((team) => teamAdminIds.has(team.id));
  const assignableProjects = canManageGuardrails
    ? projects
    : projects.filter(
        (project) => teamAdminIds.has(project.team_id) || projectAdminIds.has(project.id),
      );
  const assignableProjectIds = new Set(assignableProjects.map((project) => project.id));
  const assignableVirtualKeys = canManageGuardrails
    ? virtualKeys
    : virtualKeys.filter((key) => assignableProjectIds.has(key.project_id));
  const assignmentScopeOptions = buildScopeOptions({
    teams: assignableTeams,
    projects: assignableProjects,
    virtualKeys: assignableVirtualKeys,
    includeOrg: canManageGuardrails,
  });
  const scopeOptions = buildScopeOptions({ teams, projects, virtualKeys, includeOrg: true });
  const scopeLabels = buildScopeLabels(scopeOptions);
  const policyLabels = Object.fromEntries([
    ...policyOptions.map((policy) => [policy.id, policy.name]),
    ...policies.map((policy) => [policy.id, policy.name]),
  ]);
  const activePolicies = policies.filter((policy) => policy.is_active);
  const enforcedPolicies = policies.filter((policy) => policy.enforcement_mode === "enforce");

  const invalidateGuardrails = async () => {
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/policies"] });
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/assignments"] });
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/events"] });
    await queryClient.invalidateQueries({ queryKey: ["guardrail-policy-options"] });
  };

  const createPolicy = useCreatePolicyApiV1GuardrailsPoliciesPost({
    mutation: { onError: () => toast.error("Policy could not be saved.") },
  });
  const updatePolicy = useUpdatePolicyApiV1GuardrailsPoliciesPolicyIdPatch({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          await invalidateGuardrails();
          setPolicySheetOpen(false);
          toast.success("Guardrail policy updated.");
        }
      },
      onError: () => toast.error("Policy could not be saved."),
    },
  });
  const createAssignment = useCreateAssignmentApiV1GuardrailsAssignmentsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          await invalidateGuardrails();
          setAssignmentSheetOpen(false);
          toast.success("Policy assigned.");
        }
      },
      onError: () => toast.error("Assignment could not be saved."),
    },
  });
  const updateAssignment = useUpdateAssignmentApiV1GuardrailsAssignmentsAssignmentIdPatch({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          await invalidateGuardrails();
          setAssignmentSheetOpen(false);
          setEditingAssignment(null);
          toast.success("Assignment updated.");
        }
      },
      onError: () => toast.error("Assignment could not be saved."),
    },
  });
  const deleteAssignment = useDeleteAssignmentApiV1GuardrailsAssignmentsAssignmentIdDelete({
    mutation: {
      onSuccess: async () => {
        await invalidateGuardrails();
        toast.success("Assignment removed.");
      },
      onError: () => toast.error("Assignment could not be removed."),
    },
  });
  const deletePolicy = useDeletePolicyApiV1GuardrailsPoliciesPolicyIdDelete({
    mutation: {
      onSuccess: async () => {
        await invalidateGuardrails();
        toast.success("Policy deleted.");
      },
      onError: () => toast.error("Policy could not be deleted."),
    },
  });

  const handleDeletePolicy = (policy: GuardrailPolicyResponse) => {
    confirmWithImpact({
      title: `Delete guardrail policy "${policy.name}"?`,
      confirmLabel: "Delete policy",
      fetchImpact: () => getPolicyImpactApiV1GuardrailsPoliciesPolicyIdImpactGet(policy.id),
      onConfirm: () => deletePolicy.mutate({ policyId: policy.id }),
    });
  };
  const handleDeleteAssignment = (assignment: GuardrailAssignmentResponse) => {
    confirmWithImpact({
      title: "Remove this guardrail assignment?",
      confirmLabel: "Remove assignment",
      fetchImpact: () =>
        getAssignmentImpactApiV1GuardrailsAssignmentsAssignmentIdImpactGet(assignment.id),
      onConfirm: () => deleteAssignment.mutate({ assignmentId: assignment.id }),
    });
  };
  const toggleAssignmentActive = (assignment: GuardrailAssignmentResponse) => {
    if (assignment.is_active) {
      confirmWithImpact({
        title: "Deactivate this guardrail assignment?",
        confirmLabel: "Deactivate",
        fetchImpact: () =>
          getAssignmentImpactApiV1GuardrailsAssignmentsAssignmentIdImpactGet(assignment.id),
        onConfirm: () =>
          updateAssignment.mutate({ assignmentId: assignment.id, data: { is_active: false } }),
      });
      return;
    }
    updateAssignment.mutate({ assignmentId: assignment.id, data: { is_active: true } });
  };

  const openCreatePolicy = () => {
    setEditingPolicy(null);
    setPolicyForm(emptyPolicyForm);
    setAssignmentForm({ ...emptyAssignmentForm, scope_type: "none" });
    setPolicySheetOpen(true);
  };
  const openEditPolicy = (policy: GuardrailPolicyResponse) => {
    setEditingPolicy(policy);
    setPolicyForm({
      name: policy.name,
      description: policy.description ?? "",
      enforcement_mode: policy.enforcement_mode,
      is_active: policy.is_active,
      rules:
        policy.rules.length > 0
          ? policy.rules.map((rule) =>
              newRuleForm({
                rule_type: rule.rule_type,
                effect: rule.effect,
                phase: normalizeRulePhase(rule.rule_type, rule.phase ?? "both"),
                values: rule.values.join("\n"),
                detector: readRuleDetector(rule.config),
                matchers:
                  rule.matchers?.map((matcher) =>
                    newMatcherForm({
                      dimension: matcher.dimension,
                      operator: matcher.operator,
                      value: Array.isArray(matcher.value_json)
                        ? matcher.value_json.join("\n")
                        : matcher.value_json == null
                          ? ""
                          : String(matcher.value_json),
                    }),
                  ) ?? [],
                priority: rule.priority,
                is_active: rule.is_active,
              }),
            )
          : [newRuleForm()],
    });
    setPolicySheetOpen(true);
  };
  const openCreateAssignment = () => {
    setEditingAssignment(null);
    setAssignmentForm({
      ...emptyAssignmentForm,
      scope_type: canManageGuardrails ? "org" : firstAssignableScope(assignmentScopeOptions),
    });
    setAssignmentSheetOpen(true);
  };
  const openEditAssignment = (assignment: GuardrailAssignmentResponse) => {
    setEditingAssignment(assignment);
    setAssignmentForm({
      policy_id: assignment.policy_id,
      scope_type: assignment.scope_type,
      scope_id: assignment.team_id ?? assignment.project_id ?? assignment.virtual_key_id ?? "",
      enforcement_mode: assignment.enforcement_mode,
    });
    setAssignmentSheetOpen(true);
  };

  const buildPolicyPayload = () => {
    if (!policyForm.name.trim()) {
      toast.error("Policy name is required.");
      return null;
    }
    const rules: GuardrailRuleInput[] = [];
    for (const [index, rule] of policyForm.rules.entries()) {
      const values = parseRuleValues(rule.values);
      const validationError = validateRuleForm(rule, index, values);
      if (validationError) {
        toast.error(validationError);
        return null;
      }
      rules.push({
        rule_type: rule.rule_type,
        effect: rule.effect,
        phase: normalizeRulePhase(rule.rule_type, rule.phase),
        values,
        config: buildRuleConfig(rule),
        matchers: rule.matchers.map((matcher) => ({
          dimension: matcher.dimension,
          operator: matcher.operator,
          value_json: parseMatcherValue(matcher),
        })),
        priority: rule.priority,
        is_active: rule.is_active,
      });
    }
    return {
      name: policyForm.name.trim(),
      description: policyForm.description.trim() || null,
      enforcement_mode: policyForm.enforcement_mode,
      is_active: policyForm.is_active,
      rules,
    };
  };

  const submitPolicy = async () => {
    const payload = buildPolicyPayload();
    if (!payload) return;
    if (editingPolicy) {
      if (editingPolicy.is_active && !payload.is_active) {
        confirmWithImpact({
          title: `Deactivate guardrail policy "${editingPolicy.name}"?`,
          confirmLabel: "Deactivate policy",
          fetchImpact: () =>
            getPolicyImpactApiV1GuardrailsPoliciesPolicyIdImpactGet(editingPolicy.id),
          onConfirm: () => updatePolicy.mutate({ policyId: editingPolicy.id, data: payload }),
        });
        return;
      }
      updatePolicy.mutate({ policyId: editingPolicy.id, data: payload });
      return;
    }
    try {
      const response = await createPolicy.mutateAsync({ data: payload });
      if (response.status !== 201) return;
      const scopeType = assignmentForm.scope_type as ScopeType | "none";
      if (scopeType !== "none") {
        if (scopeType !== "org" && !assignmentForm.scope_id.trim()) {
          toast.error("Choose a scope.");
          return;
        }
        await createAssignment.mutateAsync({
          data: {
            policy_id: response.data.id,
            scope_type: scopeType,
            team_id: scopeType === "team" ? assignmentForm.scope_id : null,
            project_id: scopeType === "project" ? assignmentForm.scope_id : null,
            virtual_key_id: scopeType === "virtual_key" ? assignmentForm.scope_id : null,
            enforcement_mode: assignmentForm.enforcement_mode,
            is_active: true,
          },
        });
      }
      await invalidateGuardrails();
      setPolicySheetOpen(false);
      toast.success(
        scopeType === "none"
          ? "Guardrail policy created."
          : "Guardrail policy created and assigned.",
      );
    } catch {
      toast.error("Policy could not be saved.");
    }
  };

  const previewPolicy = () => {
    const payload = buildPolicyPayload();
    if (!payload) return;
    const scopeType = assignmentForm.scope_type as ScopeType | "none";
    if (
      !editingPolicy &&
      scopeType !== "none" &&
      scopeType !== "org" &&
      !assignmentForm.scope_id.trim()
    ) {
      toast.error("Choose a scope.");
      return;
    }
    setSimulationDrafts([
      {
        kind: "guardrail",
        operation: editingPolicy ? "replace_policy" : "add_policy",
        existing_policy_id: editingPolicy?.id ?? null,
        assignment: editingPolicy
          ? null
          : guardrailSimulationDraftAssignment(scopeType, assignmentForm),
        guardrail_policy: payload,
      },
    ]);
    setPolicySimulationResult(null);
    setPolicySheetOpen(false);
    const next = new URLSearchParams(searchParams);
    next.set("tab", "simulation");
    setSearchParams(next, { replace: true });
  };

  const submitAssignment = () => {
    if (!assignmentForm.policy_id) {
      toast.error("Choose a policy to assign.");
      return;
    }
    const scopeType = assignmentForm.scope_type as ScopeType;
    if (scopeType !== "org" && !assignmentForm.scope_id.trim()) {
      toast.error("Choose a scope.");
      return;
    }
    const scopeTargets = assignmentScopeOptions[scopeType] ?? [];
    if (scopeType !== "org" && scopeTargets.length === 0) {
      toast.error(`No ${scopeType.replace("_", " ")} targets are available.`);
      return;
    }
    const data = {
      policy_id: assignmentForm.policy_id,
      scope_type: scopeType,
      team_id: scopeType === "team" ? assignmentForm.scope_id : null,
      project_id: scopeType === "project" ? assignmentForm.scope_id : null,
      virtual_key_id: scopeType === "virtual_key" ? assignmentForm.scope_id : null,
      enforcement_mode: assignmentForm.enforcement_mode,
      is_active: editingAssignment?.is_active ?? true,
    };
    if (editingAssignment) {
      updateAssignment.mutate({ assignmentId: editingAssignment.id, data });
    } else {
      createAssignment.mutate({ data });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Guardrails"
        description="Composable request and response policies that inspect and block unsafe content."
        actions={
          canAssignGuardrails || canManageGuardrails ? (
            <div className="flex gap-2">
              {canAssignGuardrails ? (
                <Button variant="outline" onClick={openCreateAssignment}>
                  <Plus data-icon="inline-start" />
                  Assign existing policy
                </Button>
              ) : null}
              {canManageGuardrails ? (
                <Button onClick={openCreatePolicy}>
                  <Plus data-icon="inline-start" />
                  New guardrail policy
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="Active policies" value={activePolicies.length} icon={ShieldCheck} />
        <StatCard label="Enforced policies" value={enforcedPolicies.length} icon={Shield} />
        <StatCard label="Recent blocks" value={recentBlockCount} icon={ShieldX} />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const next = new URLSearchParams(searchParams);
          if (value === "policies") next.delete("tab");
          else next.set("tab", value);
          setSearchParams(next, { replace: true });
        }}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="policies">Policies</TabsTrigger>
          <TabsTrigger value="assignments">Assignments</TabsTrigger>
          <TabsTrigger value="simulation">Simulation</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
        </TabsList>

        <TabsContent value="policies">
          <GuardrailPoliciesTab
            policies={policies}
            isLoading={policiesQuery.isPending}
            canManage={canManageGuardrails}
            onCreate={openCreatePolicy}
            onEdit={openEditPolicy}
            onDelete={handleDeletePolicy}
            deletePending={deletePolicy.isPending}
          />
        </TabsContent>

        <TabsContent value="assignments">
          <GuardrailAssignmentsTab
            assignments={assignments}
            isLoading={assignmentsQuery.isPending}
            canAssign={canAssignGuardrails}
            scopeLabels={scopeLabels}
            onEdit={openEditAssignment}
            onToggleActive={toggleAssignmentActive}
            onRemove={handleDeleteAssignment}
            togglePending={updateAssignment.isPending}
            removePending={deleteAssignment.isPending}
          />
        </TabsContent>

        <TabsContent value="simulation">
          <GuardrailSimulationTab
            policies={policies}
            policySimulationDrafts={simulationDrafts}
            policySimulationResult={policySimulationResult}
            onPolicySimulationResult={setPolicySimulationResult}
          />
        </TabsContent>

        <TabsContent value="events">
          <GuardrailEventsTab
            policies={policies}
            policyLabels={policyLabels}
            scopeOptions={scopeOptions}
            scopeLabels={scopeLabels}
          />
        </TabsContent>
      </Tabs>

      <GuardrailPolicySheet
        open={policySheetOpen}
        onOpenChange={setPolicySheetOpen}
        editingPolicy={editingPolicy}
        form={policyForm}
        setForm={setPolicyForm}
        assignmentForm={assignmentForm}
        setAssignmentForm={setAssignmentForm}
        assignmentScopeOptions={assignmentScopeOptions}
        onSubmit={submitPolicy}
        onPreview={previewPolicy}
        isPending={createPolicy.isPending || updatePolicy.isPending}
      />

      <GuardrailAssignmentSheet
        open={assignmentSheetOpen}
        onOpenChange={(open) => {
          setAssignmentSheetOpen(open);
          if (!open) setEditingAssignment(null);
        }}
        editingAssignment={editingAssignment}
        form={assignmentForm}
        setForm={setAssignmentForm}
        policies={policies}
        policyOptions={policyOptions}
        policyLabels={policyLabels}
        assignmentScopeOptions={assignmentScopeOptions}
        scopeLabels={scopeLabels}
        onSubmit={submitAssignment}
        isPending={createAssignment.isPending || updateAssignment.isPending}
      />

      {impactDialog}
    </div>
  );
}

function guardrailSimulationDraftAssignment(
  scopeType: ScopeType | "none",
  assignmentForm: AssignmentFormState,
): PolicySimulationDraft["assignment"] {
  if (scopeType === "none") return null;
  return {
    scope_type: scopeType,
    team_id: scopeType === "team" ? assignmentForm.scope_id : null,
    project_id: scopeType === "project" ? assignmentForm.scope_id : null,
    virtual_key_id: scopeType === "virtual_key" ? assignmentForm.scope_id : null,
    guardrail_assignment_mode:
      assignmentForm.enforcement_mode === "dry_run" ? "dry_run" : "enforce",
  };
}
