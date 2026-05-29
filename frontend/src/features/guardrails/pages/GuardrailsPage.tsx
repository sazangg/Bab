import { useQueries, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, ShieldCheck, ShieldX, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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
import { hasPermission } from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  useCreateAssignmentApiV1GuardrailsAssignmentsPost,
  useCreatePolicyApiV1GuardrailsPoliciesPost,
  useDeleteAssignmentApiV1GuardrailsAssignmentsAssignmentIdDelete,
  useDeletePolicyApiV1GuardrailsPoliciesPolicyIdDelete,
  useListAssignmentsApiV1GuardrailsAssignmentsGet,
  useListEventsApiV1GuardrailsEventsGet,
  useListPoliciesApiV1GuardrailsPoliciesGet,
  useSimulateGuardrailsApiV1GuardrailsSimulatePost,
  useUpdateAssignmentApiV1GuardrailsAssignmentsAssignmentIdPatch,
  useUpdatePolicyApiV1GuardrailsPoliciesPolicyIdPatch,
} from "@/shared/api/generated/guardrails/guardrails";
import {
  listVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useListAllocationsApiV1ProjectsAllocationsGet,
  useListProjectsApiV1ProjectsGet,
} from "@/shared/api/generated/projects/projects";
import type {
  AllocationResponse,
  GuardrailAssignmentResponse,
  GuardrailEventResponse,
  GuardrailPolicyResponse,
  GuardrailRuleInput,
  GuardrailSimulationResponse,
  ProjectResponse,
  TeamResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

const emptyPolicyForm = {
  name: "",
  description: "",
  enforcement_mode: "enforce",
  is_active: true,
  rules: [newRuleForm()],
};

const emptyAssignmentForm = {
  policy_id: "",
  scope_type: "org",
  scope_id: "",
  enforcement_mode: "enforce",
};

const ruleTypeOptions = ["model", "provider", "pool", "prompt_contains", "prompt_regex", "pii"];
const ruleTypeLabels: Record<string, string> = {
  model: "Model",
  provider: "Provider",
  pool: "Pool",
  prompt_contains: "Prompt keyword",
  prompt_regex: "Prompt regex",
  pii: "PII detector",
};

type ScopeType = "org" | "team" | "project" | "allocation" | "virtual_key";
type EventScopeType = "all" | ScopeType;
type ScopeOption = { id: string; label: string };
type ScopeOptions = Record<ScopeType, ScopeOption[]>;
type ScopedVirtualKey = VirtualKeyResponse & { project_name: string };
type PolicyRuleForm = {
  id: string;
  rule_type: string;
  effect: string;
  values: string;
  detector: string;
  priority: number;
  is_active: boolean;
};

function newRuleForm(overrides: Partial<PolicyRuleForm> = {}): PolicyRuleForm {
  return {
    id: crypto.randomUUID(),
    rule_type: "model",
    effect: "allow",
    values: "",
    detector: "local_regex",
    priority: 100,
    is_active: true,
    ...overrides,
  };
}

export function GuardrailsPage() {
  const queryClient = useQueryClient();
  const [policySheetOpen, setPolicySheetOpen] = useState(false);
  const [assignmentSheetOpen, setAssignmentSheetOpen] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<GuardrailPolicyResponse | null>(null);
  const [editingAssignment, setEditingAssignment] = useState<GuardrailAssignmentResponse | null>(
    null,
  );
  const [eventDecision, setEventDecision] = useState("all");
  const [eventPolicyId, setEventPolicyId] = useState("all");
  const [eventScopeType, setEventScopeType] = useState<EventScopeType>("all");
  const [eventScopeId, setEventScopeId] = useState("all");
  const [eventModel, setEventModel] = useState("");
  const [simulationPolicyId, setSimulationPolicyId] = useState("");
  const [simulationModel, setSimulationModel] = useState("gpt-5-mini");
  const [simulationPrompt, setSimulationPrompt] = useState("");
  const [simulationResult, setSimulationResult] = useState<GuardrailSimulationResponse | null>(
    null,
  );
  const [policyForm, setPolicyForm] = useState(emptyPolicyForm);
  const [assignmentForm, setAssignmentForm] = useState(emptyAssignmentForm);
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageGuardrails = hasPermission(currentUser, "guardrails.manage");
  const policiesQuery = useListPoliciesApiV1GuardrailsPoliciesGet();
  const assignmentsQuery = useListAssignmentsApiV1GuardrailsAssignmentsGet();
  const eventsQuery = useListEventsApiV1GuardrailsEventsGet({
    decision: eventDecision === "all" ? undefined : eventDecision,
    policy_id: eventPolicyId === "all" ? undefined : eventPolicyId,
    team_id: eventScopeType === "team" && eventScopeId !== "all" ? eventScopeId : undefined,
    project_id: eventScopeType === "project" && eventScopeId !== "all" ? eventScopeId : undefined,
    allocation_id:
      eventScopeType === "allocation" && eventScopeId !== "all" ? eventScopeId : undefined,
    virtual_key_id:
      eventScopeType === "virtual_key" && eventScopeId !== "all" ? eventScopeId : undefined,
    model: eventModel.trim() || undefined,
    limit: 50,
  });
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const allocationsQuery = useListAllocationsApiV1ProjectsAllocationsGet();
  const policies = policiesQuery.data?.status === 200 ? policiesQuery.data.data : [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const events = eventsQuery.data?.status === 200 ? eventsQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const allocations = allocationsQuery.data?.status === 200 ? allocationsQuery.data.data : [];
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
  const scopeOptions = buildScopeOptions({ teams, projects, allocations, virtualKeys });
  const scopeLabels = buildScopeLabels(scopeOptions);
  const policyLabels = Object.fromEntries(policies.map((policy) => [policy.id, policy.name]));
  const activePolicies = policies.filter((policy) => policy.is_active);
  const enforcedPolicies = policies.filter((policy) => policy.enforcement_mode === "enforce");
  const blockedEvents = events.filter((event) => event.decision === "blocked");
  const selectedAssignmentPolicy = policies.find(
    (policy) => policy.id === assignmentForm.policy_id,
  );
  const selectedAssignmentScope =
    assignmentForm.scope_type === "org"
      ? "Organization"
      : scopeLabels[assignmentForm.scope_id] || "No target selected";
  const selectedAssignmentScopeOptions = scopeOptions[assignmentForm.scope_type as ScopeType] ?? [];
  const eventScopeOptions = eventScopeType === "all" ? [] : scopeOptions[eventScopeType];

  const invalidateGuardrails = async () => {
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/policies"] });
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/assignments"] });
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/guardrails/events"] });
  };

  const createPolicy = useCreatePolicyApiV1GuardrailsPoliciesPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          await invalidateGuardrails();
          setPolicySheetOpen(false);
          toast.success("Guardrail policy created.");
        }
      },
      onError: () => toast.error("Policy could not be saved."),
    },
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
  const simulateGuardrails = useSimulateGuardrailsApiV1GuardrailsSimulatePost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 200) {
          setSimulationResult(response.data);
        }
      },
      onError: () => toast.error("Simulation could not be run."),
    },
  });

  const policyRows = policies.map((policy) => ({
    ...policy,
    summary: policy.rules
      .map(
        (rule) =>
          `${rule.effect} ${ruleTypeLabels[rule.rule_type] ?? rule.rule_type}: ${rule.values.join(", ")}`,
      )
      .join(" · "),
  }));

  const openCreatePolicy = () => {
    setEditingPolicy(null);
    setPolicyForm(emptyPolicyForm);
    setPolicySheetOpen(true);
  };

  const openCreateAssignment = () => {
    setEditingAssignment(null);
    setAssignmentForm(emptyAssignmentForm);
    setAssignmentSheetOpen(true);
  };

  const openEditAssignment = (assignment: GuardrailAssignmentResponse) => {
    setEditingAssignment(assignment);
    setAssignmentForm({
      policy_id: assignment.policy_id,
      scope_type: assignment.scope_type,
      scope_id:
        assignment.team_id ??
        assignment.project_id ??
        assignment.allocation_id ??
        assignment.virtual_key_id ??
        "",
      enforcement_mode: assignment.enforcement_mode,
    });
    setAssignmentSheetOpen(true);
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
                values: rule.values.join("\n"),
                detector: readRuleDetector(rule.config),
                priority: rule.priority,
                is_active: rule.is_active,
              }),
            )
          : [newRuleForm()],
    });
    setPolicySheetOpen(true);
  };

  const submitPolicy = () => {
    if (!policyForm.name.trim()) {
      toast.error("Policy name is required.");
      return;
    }
    const rules: GuardrailRuleInput[] = [];
    for (const [index, rule] of policyForm.rules.entries()) {
      const values = parseRuleValues(rule.values);
      if (values.length === 0) {
        toast.error(`Rule ${index + 1} needs at least one value.`);
        return;
      }
      rules.push({
        rule_type: rule.rule_type,
        effect: rule.effect,
        values,
        config: buildRuleConfig(rule),
        priority: rule.priority,
        is_active: rule.is_active,
      });
    }
    const payload = {
      name: policyForm.name.trim(),
      description: policyForm.description.trim() || null,
      enforcement_mode: policyForm.enforcement_mode,
      is_active: policyForm.is_active,
      rules,
    };
    if (editingPolicy) {
      updatePolicy.mutate({ policyId: editingPolicy.id, data: payload });
    } else {
      createPolicy.mutate({ data: payload });
    }
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
    if (scopeType !== "org" && selectedAssignmentScopeOptions.length === 0) {
      toast.error(`No ${scopeType.replace("_", " ")} targets are available.`);
      return;
    }
    const data = {
      policy_id: assignmentForm.policy_id,
      scope_type: scopeType,
      team_id: scopeType === "team" ? assignmentForm.scope_id : null,
      project_id: scopeType === "project" ? assignmentForm.scope_id : null,
      allocation_id: scopeType === "allocation" ? assignmentForm.scope_id : null,
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

  const runSimulation = () => {
    if (!simulationPolicyId) {
      toast.error("Choose a policy to simulate.");
      return;
    }
    if (!simulationModel.trim()) {
      toast.error("Model is required.");
      return;
    }
    simulateGuardrails.mutate({
      data: {
        policy_id: simulationPolicyId,
        requested_model: simulationModel.trim(),
        prompt_text: simulationPrompt,
      },
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Guardrails"
        description="Composable request policies that constrain models, providers, and pools."
        actions={
          canManageGuardrails ? (
            <div className="flex gap-2">
              <Button variant="outline" onClick={openCreateAssignment}>
                <Plus data-icon="inline-start" />
                Assign policy
              </Button>
              <Button onClick={openCreatePolicy}>
                <Plus data-icon="inline-start" />
                New policy
              </Button>
            </div>
          ) : null
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        <SummaryCard label="Active policies" value={activePolicies.length} />
        <SummaryCard label="Enforced policies" value={enforcedPolicies.length} />
        <SummaryCard label="Recent blocks" value={blockedEvents.length} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Simulation</CardTitle>
          <CardDescription>
            Test a policy against a model and prompt without recording an event or sending traffic.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
            <div className="grid gap-3">
              <div className="grid gap-3 md:grid-cols-2">
                <SelectField
                  label="Policy"
                  value={simulationPolicyId}
                  onValueChange={setSimulationPolicyId}
                  options={policies.map((policy) => policy.id)}
                  labels={Object.fromEntries(policies.map((policy) => [policy.id, policy.name]))}
                  placeholder="Choose policy"
                />
                <Field label="Requested model">
                  <Input
                    value={simulationModel}
                    onChange={(event) => setSimulationModel(event.target.value)}
                  />
                </Field>
              </div>
              <Field label="Prompt">
                <Textarea
                  value={simulationPrompt}
                  onChange={(event) => setSimulationPrompt(event.target.value)}
                  className="min-h-28 resize-none"
                  placeholder="Paste a prompt to test prompt and PII rules"
                />
              </Field>
              <div>
                <Button onClick={runSimulation} disabled={simulateGuardrails.isPending}>
                  <ShieldCheck data-icon="inline-start" />
                  Run simulation
                </Button>
              </div>
            </div>
            <div className="rounded-md border bg-muted/20 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Result</div>
                {simulationResult ? (
                  <Badge
                    variant={simulationResult.decision === "blocked" ? "destructive" : "outline"}
                  >
                    {simulationResult.decision}
                  </Badge>
                ) : (
                  <Badge variant="outline">Not run</Badge>
                )}
              </div>
              <div className="mt-3 grid gap-2 text-sm">
                {simulationResult ? (
                  simulationResult.matches.length > 0 ? (
                    simulationResult.matches.map((match, index) => (
                      <div
                        key={`${match.reason}-${index}`}
                        className="rounded-md bg-background p-3"
                      >
                        <div className="font-medium">
                          {ruleTypeLabels[match.rule_type] ?? match.rule_type} · {match.effect}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {match.reason} · priority {match.priority}
                        </div>
                        <div className="mt-2 font-mono text-xs">
                          {match.matched_values.length > 0
                            ? match.matched_values.join(", ")
                            : "No direct value match"}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-muted-foreground">No rules would block this request.</p>
                  )
                ) : (
                  <p className="text-muted-foreground">
                    Simulation results will show matched rules and dry-run decisions here.
                  </p>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {policiesQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading guardrails...</p>
      ) : policies.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No guardrails yet"
          description="Create a policy to start constraining routing by model, provider, or pool."
          action={
            canManageGuardrails ? (
              <Button onClick={openCreatePolicy}>
                <Plus data-icon="inline-start" />
                New policy
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Policies</CardTitle>
            <CardDescription>Policies are restrictive when assigned across scopes.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Policy</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Rules</TableHead>
                  <TableHead>Status</TableHead>
                  {canManageGuardrails ? (
                    <TableHead className="w-24 text-right">Actions</TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {policyRows.map((policy) => (
                  <TableRow key={policy.id}>
                    <TableCell>
                      <div className="font-medium">{policy.name}</div>
                      <div className="text-sm text-muted-foreground">
                        {policy.description ?? "No description"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={policy.enforcement_mode === "enforce" ? "default" : "outline"}
                      >
                        {policy.enforcement_mode}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xl">
                      <span className="line-clamp-2 text-sm text-muted-foreground">
                        {policy.summary || "No rules"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <StatusBadge variant={policy.is_active ? "active" : "inactive"}>
                        {policy.is_active ? "Active" : "Inactive"}
                      </StatusBadge>
                    </TableCell>
                    {canManageGuardrails ? (
                      <TableCell className="text-right">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Actions for ${policy.name}`}
                            >
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => openEditPolicy(policy)}>
                              <Pencil />
                              Edit policy
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onSelect={() => deletePolicy.mutate({ policyId: policy.id })}
                              disabled={deletePolicy.isPending}
                            >
                              <Trash2 />
                              Delete policy
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Assignments</CardTitle>
            <CardDescription>Effective guardrails compose from org down to keys.</CardDescription>
          </CardHeader>
          <CardContent>
            {assignments.length === 0 ? (
              <EmptyState
                icon={ShieldCheck}
                title="No assignments"
                description="Assign a policy to org, team, project, allocation, or virtual key."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Policy</TableHead>
                    <TableHead>Scope</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Status</TableHead>
                    {canManageGuardrails ? (
                      <TableHead className="w-12">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    ) : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assignments.map((assignment) => (
                    <TableRow key={assignment.id}>
                      <TableCell className="font-medium">{assignment.policy_name}</TableCell>
                      <TableCell>
                        <div>{assignment.scope_type}</div>
                        <div className="text-xs text-muted-foreground">
                          {labelAssignmentScope(assignment, scopeLabels)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={assignment.enforcement_mode === "dry_run" ? "outline" : "secondary"}>
                          {assignment.enforcement_mode === "dry_run" ? "Dry run" : "Enforce"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
                          {assignment.is_active ? "Active" : "Inactive"}
                        </StatusBadge>
                      </TableCell>
                      {canManageGuardrails ? (
                        <TableCell className="text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={`Actions for ${assignment.policy_name}`}
                              >
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onSelect={() => openEditAssignment(assignment)}>
                                <Pencil />
                                Edit assignment
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() =>
                                  updateAssignment.mutate({
                                    assignmentId: assignment.id,
                                    data: { is_active: !assignment.is_active },
                                  })
                                }
                                disabled={updateAssignment.isPending}
                              >
                                {assignment.is_active
                                  ? "Deactivate assignment"
                                  : "Activate assignment"}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                variant="destructive"
                                onSelect={() =>
                                  deleteAssignment.mutate({ assignmentId: assignment.id })
                                }
                                disabled={deleteAssignment.isPending}
                              >
                                <Trash2 />
                                Remove assignment
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>Recent events</CardTitle>
                <CardDescription>
                  Append-only guardrail decisions from proxy traffic.
                </CardDescription>
              </div>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              <Select value={eventDecision} onValueChange={setEventDecision}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All decisions</SelectItem>
                  <SelectItem value="allowed">Allowed</SelectItem>
                  <SelectItem value="dry_run">Dry run</SelectItem>
                  <SelectItem value="blocked">Blocked</SelectItem>
                </SelectContent>
              </Select>
              <Select value={eventPolicyId} onValueChange={setEventPolicyId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All policies</SelectItem>
                  {policies.map((policy) => (
                    <SelectItem key={policy.id} value={policy.id}>
                      {policy.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={eventScopeType}
                onValueChange={(value) => {
                  setEventScopeType(value as EventScopeType);
                  setEventScopeId("all");
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All scopes</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                  <SelectItem value="allocation">Allocation</SelectItem>
                  <SelectItem value="virtual_key">Virtual key</SelectItem>
                </SelectContent>
              </Select>
              <Input
                value={eventModel}
                onChange={(event) => setEventModel(event.target.value)}
                placeholder="Filter model"
              />
              {eventScopeType !== "all" ? (
                <div className="md:col-span-2 xl:col-span-4">
                  <Select value={eventScopeId} onValueChange={setEventScopeId}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All {eventScopeType.replace("_", " ")}s</SelectItem>
                      {eventScopeOptions.map((option) => (
                        <SelectItem key={option.id} value={option.id}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
            </div>
          </CardHeader>
          <CardContent>
            {events.length === 0 ? (
              <EmptyState
                icon={ShieldX}
                title="No guardrail events"
                description="Events appear when proxied requests pass or fail assigned policies."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Decision</TableHead>
                    <TableHead>Policy</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Scope</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.slice(0, 8).map((event) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <Badge variant={event.decision === "blocked" ? "destructive" : "outline"}>
                          {event.decision}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div>
                          {event.policy_id ? (policyLabels[event.policy_id] ?? "Policy") : "-"}
                        </div>
                        <div className="text-xs text-muted-foreground">{event.reason}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {event.requested_model ?? "-"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {labelEventScope(event, scopeLabels)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <Sheet open={policySheetOpen} onOpenChange={setPolicySheetOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{editingPolicy ? "Edit policy" : "New policy"}</SheetTitle>
            <SheetDescription>
              Policies can include multiple rules. Any enabled rule that denies a request blocks it
              in enforce mode.
            </SheetDescription>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <div className="grid gap-6">
              <section className="grid gap-4">
                <div>
                  <h3 className="text-sm font-medium">Policy details</h3>
                  <p className="text-sm text-muted-foreground">
                    Name the policy and choose whether it actively blocks traffic.
                  </p>
                </div>
                <Field label="Name">
                  <Input
                    value={policyForm.name}
                    onChange={(event) => setPolicyForm({ ...policyForm, name: event.target.value })}
                  />
                </Field>
                <Field label="Description">
                  <Textarea
                    value={policyForm.description}
                    onChange={(event) =>
                      setPolicyForm({ ...policyForm, description: event.target.value })
                    }
                    className="min-h-24 resize-none"
                  />
                </Field>
                <div className="flex items-center justify-between gap-4 rounded-md border p-3">
                  <div>
                    <Label htmlFor="guardrail-policy-active">Policy is active</Label>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Inactive policies stay configured but are ignored during enforcement.
                    </p>
                  </div>
                  <Switch
                    id="guardrail-policy-active"
                    checked={policyForm.is_active}
                    onCheckedChange={(checked) =>
                      setPolicyForm({ ...policyForm, is_active: checked })
                    }
                  />
                </div>
              </section>

              <section className="grid gap-4">
                <div>
                  <h3 className="text-sm font-medium">Rules</h3>
                  <p className="text-sm text-muted-foreground">
                    Allow rules define permitted sets. Deny rules block matching values. Rules are
                    evaluated in priority order.
                  </p>
                </div>
                <SelectField
                  label="Mode"
                  value={policyForm.enforcement_mode}
                  onValueChange={(value) =>
                    setPolicyForm({ ...policyForm, enforcement_mode: value })
                  }
                  options={["enforce", "monitor"]}
                />
                <div className="grid gap-3">
                  {policyForm.rules.map((rule, index) => (
                    <RuleEditor
                      key={rule.id}
                      rule={rule}
                      index={index}
                      canRemove={policyForm.rules.length > 1}
                      onChange={(nextRule) =>
                        setPolicyForm({
                          ...policyForm,
                          rules: policyForm.rules.map((item) =>
                            item.id === rule.id ? nextRule : item,
                          ),
                        })
                      }
                      onRemove={() =>
                        setPolicyForm({
                          ...policyForm,
                          rules: policyForm.rules.filter((item) => item.id !== rule.id),
                        })
                      }
                    />
                  ))}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    setPolicyForm({
                      ...policyForm,
                      rules: [...policyForm.rules, newRuleForm()],
                    })
                  }
                >
                  <Plus data-icon="inline-start" />
                  Add rule
                </Button>
              </section>
            </div>
          </div>
          <SheetFooter>
            <Button
              variant="outline"
              onClick={() => setPolicySheetOpen(false)}
              disabled={createPolicy.isPending || updatePolicy.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={submitPolicy}
              disabled={createPolicy.isPending || updatePolicy.isPending}
            >
              {editingPolicy ? "Save policy" : "Create policy"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <Sheet
        open={assignmentSheetOpen}
        onOpenChange={(open) => {
          setAssignmentSheetOpen(open);
          if (!open) setEditingAssignment(null);
        }}
      >
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{editingAssignment ? "Edit assignment" : "Assign policy"}</SheetTitle>
            <SheetDescription>
              Assignments compose restrictively across org, team, project, allocation, and key.
            </SheetDescription>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <div className="grid gap-4">
              <SelectField
                label="Policy"
                value={assignmentForm.policy_id}
                onValueChange={(value) =>
                  setAssignmentForm({ ...assignmentForm, policy_id: value })
                }
                options={policies.map((policy) => policy.id)}
                labels={Object.fromEntries(policies.map((policy) => [policy.id, policy.name]))}
              />
              <SelectField
                label="Scope"
                value={assignmentForm.scope_type}
                onValueChange={(value) =>
                  setAssignmentForm({
                    ...assignmentForm,
                    scope_type: value as ScopeType,
                    scope_id: "",
                  })
                }
                options={["org", "team", "project", "allocation", "virtual_key"]}
              />
              {assignmentForm.scope_type !== "org" ? (
                <div className="grid gap-2">
                  <SelectField
                    label="Target"
                    value={assignmentForm.scope_id}
                    onValueChange={(value) =>
                      setAssignmentForm({ ...assignmentForm, scope_id: value })
                    }
                    options={scopeOptions[assignmentForm.scope_type as ScopeType].map(
                      (option) => option.id,
                    )}
                    labels={Object.fromEntries(
                      scopeOptions[assignmentForm.scope_type as ScopeType].map((option) => [
                        option.id,
                        option.label,
                      ]),
                    )}
                    placeholder="Choose target"
                  />
                  <p className="text-xs text-muted-foreground">
                    {selectedAssignmentScopeOptions.length === 0
                      ? `No ${assignmentForm.scope_type.replace("_", " ")} targets are available yet.`
                      : "Select the exact workspace object this policy should constrain."}
                  </p>
                </div>
              ) : null}
              <SelectField
                label="Mode"
                value={assignmentForm.enforcement_mode}
                onValueChange={(value) =>
                  setAssignmentForm({ ...assignmentForm, enforcement_mode: value })
                }
                options={["enforce", "dry_run"]}
                labels={{ enforce: "Enforce", dry_run: "Dry run / log only" }}
              />
              <p className="-mt-2 text-xs text-muted-foreground">
                Dry-run assignments evaluate and log matches without blocking requests.
              </p>
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="text-sm font-medium">Assignment preview</div>
                <div className="mt-2 grid gap-1 text-sm text-muted-foreground">
                  <div>
                    Policy:{" "}
                    <span className="text-foreground">
                      {selectedAssignmentPolicy?.name ?? "No policy selected"}
                    </span>
                  </div>
                  <div>
                    Scope: <span className="text-foreground">{selectedAssignmentScope}</span>
                  </div>
                  <div>
                    Rules:{" "}
                    <span className="text-foreground">
                      {selectedAssignmentPolicy
                        ? `${selectedAssignmentPolicy.rules.filter((rule) => rule.is_active).length} active`
                        : "-"}
                    </span>
                  </div>
                  <div>
                    Mode:{" "}
                    <span className="text-foreground">
                      {assignmentForm.enforcement_mode === "dry_run" ? "Dry run" : "Enforce"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setAssignmentSheetOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submitAssignment}
              disabled={createAssignment.isPending || updateAssignment.isPending}
            >
              {editingAssignment ? "Save assignment" : "Assign policy"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function RuleEditor({
  rule,
  index,
  canRemove,
  onChange,
  onRemove,
}: {
  rule: PolicyRuleForm;
  index: number;
  canRemove: boolean;
  onChange: (rule: PolicyRuleForm) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid gap-4 rounded-md border bg-background p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">Rule {index + 1}</div>
          <div className="text-xs text-muted-foreground">
            Any enabled rule can block a request when this policy is enforced.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground" htmlFor={`guardrail-rule-${rule.id}`}>
            Active
          </Label>
          <Switch
            id={`guardrail-rule-${rule.id}`}
            checked={rule.is_active}
            onCheckedChange={(checked) => onChange({ ...rule, is_active: checked })}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={!canRemove}
            onClick={onRemove}
            aria-label={`Remove rule ${index + 1}`}
          >
            <Trash2 />
          </Button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_7rem]">
        <SelectField
          label="Rule"
          value={rule.rule_type}
          onValueChange={(value) => onChange({ ...rule, rule_type: value })}
          options={ruleTypeOptions}
          labels={ruleTypeLabels}
        />
        <SelectField
          label="Effect"
          value={rule.effect}
          onValueChange={(value) => onChange({ ...rule, effect: value })}
          options={["allow", "deny"]}
        />
        <Field label="Priority">
          <Input
            type="number"
            min={1}
            value={rule.priority}
            onChange={(event) => onChange({ ...rule, priority: Number(event.target.value) || 100 })}
          />
        </Field>
      </div>
      <Field label="Values">
        <Textarea
          value={rule.values}
          onChange={(event) => onChange({ ...rule, values: event.target.value })}
          placeholder={ruleValuePlaceholder(rule.rule_type)}
          className="min-h-28 font-mono text-sm"
        />
      </Field>
      {rule.rule_type === "pii" ? (
        <SelectField
          label="Detector"
          value={rule.detector}
          onValueChange={(value) => onChange({ ...rule, detector: value })}
          options={["local_regex"]}
          labels={{ local_regex: "Local regex" }}
        />
      ) : null}
    </div>
  );
}

function ruleValuePlaceholder(ruleType: string) {
  if (ruleType === "pii") return "email\nphone\ncredit_card";
  if (ruleType === "prompt_regex") return "secret|confidential";
  if (ruleType === "prompt_contains") return "internal roadmap";
  if (ruleType === "model") return "gpt-5-mini";
  return "One UUID per line";
}

function buildRuleConfig(rule: PolicyRuleForm) {
  if (rule.rule_type !== "pii") return {};
  return { detector: rule.detector || "local_regex" };
}

function readRuleDetector(config: unknown) {
  if (config && typeof config === "object" && "detector" in config) {
    const detector = (config as { detector?: unknown }).detector;
    if (typeof detector === "string" && detector) return detector;
  }
  return "local_regex";
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
  placeholder,
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
          {options.map((option) => {
            const label = labels[option] ?? option;
            return (
              <SelectItem key={option} value={option}>
                <span className="block max-w-[34rem] truncate">{label}</span>
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
    </Field>
  );
}

function parseRuleValues(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildScopeOptions({
  teams,
  projects,
  allocations,
  virtualKeys,
}: {
  teams: TeamResponse[];
  projects: ProjectResponse[];
  allocations: AllocationResponse[];
  virtualKeys: ScopedVirtualKey[];
}): ScopeOptions {
  const projectById = Object.fromEntries(projects.map((project) => [project.id, project]));
  return {
    org: [{ id: "org", label: "Organization" }],
    team: teams.map((team) => ({ id: team.id, label: team.name })),
    project: projects.map((project) => ({ id: project.id, label: project.name })),
    allocation: allocations.map((allocation) => {
      const projectName = allocation.project_id
        ? projectById[allocation.project_id]?.name
        : undefined;
      const owner = projectName ?? allocation.target_type;
      return {
        id: allocation.id,
        label: `${allocation.name} · ${owner}`,
      };
    }),
    virtual_key: virtualKeys.map((key) => ({
      id: key.id,
      label: `${key.name} · ${key.project_name} · ${key.key_prefix}`,
    })),
  };
}

function buildScopeLabels(scopeOptions: ScopeOptions) {
  return Object.fromEntries(
    Object.values(scopeOptions)
      .flat()
      .map((option) => [option.id, option.label]),
  );
}

function labelAssignmentScope(
  assignment: GuardrailAssignmentResponse,
  scopeLabels: Record<string, string>,
) {
  const scopeId =
    assignment.team_id ??
    assignment.project_id ??
    assignment.allocation_id ??
    assignment.virtual_key_id;
  if (!scopeId) return "Organization";
  return scopeLabels[scopeId] ?? scopeId;
}

function labelEventScope(event: GuardrailEventResponse, scopeLabels: Record<string, string>) {
  const scopeId =
    event.virtual_key_id ?? event.allocation_id ?? event.project_id ?? event.team_id ?? null;
  if (!scopeId) return "Organization";
  return scopeLabels[scopeId] ?? scopeId;
}
