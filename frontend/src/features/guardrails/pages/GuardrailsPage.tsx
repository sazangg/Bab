import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
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
import {
  useCreateAssignmentApiV1GuardrailsAssignmentsPost,
  useCreatePolicyApiV1GuardrailsPoliciesPost,
  useListAssignmentsApiV1GuardrailsAssignmentsGet,
  useListEventsApiV1GuardrailsEventsGet,
  useListPoliciesApiV1GuardrailsPoliciesGet,
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
  GuardrailPolicyResponse,
  GuardrailRuleInput,
  ProjectResponse,
  TeamResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
import { apiMutator } from "@/shared/api/orval-mutator";
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
};

type ScopeType = "org" | "team" | "project" | "allocation" | "virtual_key";
type ScopeOption = { id: string; label: string };
type ScopeOptions = Record<ScopeType, ScopeOption[]>;
type ScopedVirtualKey = VirtualKeyResponse & { project_name: string };
type PolicyRuleForm = {
  id: string;
  rule_type: string;
  effect: string;
  values: string;
  priority: number;
  is_active: boolean;
};

function newRuleForm(overrides: Partial<PolicyRuleForm> = {}): PolicyRuleForm {
  return {
    id: crypto.randomUUID(),
    rule_type: "model",
    effect: "allow",
    values: "",
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
  const [policyForm, setPolicyForm] = useState(emptyPolicyForm);
  const [assignmentForm, setAssignmentForm] = useState(emptyAssignmentForm);
  const policiesQuery = useListPoliciesApiV1GuardrailsPoliciesGet();
  const assignmentsQuery = useListAssignmentsApiV1GuardrailsAssignmentsGet();
  const eventsQuery = useListEventsApiV1GuardrailsEventsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const allocationsQuery = useListAllocationsApiV1ProjectsAllocationsGet();
  const policies = policiesQuery.data?.status === 200 ? policiesQuery.data.data : [];
  const assignments = assignmentsQuery.data?.status === 200 ? assignmentsQuery.data.data : [];
  const events = eventsQuery.data?.status === 200 ? eventsQuery.data.data : [];
  const filteredEvents =
    eventDecision === "all" ? events : events.filter((event) => event.decision === eventDecision);
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
  const deleteAssignment = useMutation({
    mutationFn: (assignmentId: string) =>
      apiMutator(`/api/v1/guardrails/assignments/${assignmentId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidateGuardrails();
      toast.success("Assignment removed.");
    },
    onError: () => toast.error("Assignment could not be removed."),
  });
  const deletePolicy = useMutation({
    mutationFn: (policyId: string) =>
      apiMutator(`/api/v1/guardrails/policies/${policyId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidateGuardrails();
      toast.success("Policy deleted.");
    },
    onError: () => toast.error("Policy could not be deleted."),
  });

  const policyRows = policies.map((policy) => ({
    ...policy,
    summary: policy.rules
      .map((rule) => `${rule.effect} ${rule.rule_type}: ${rule.values.join(", ")}`)
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
    const data = {
      policy_id: assignmentForm.policy_id,
      scope_type: scopeType,
      team_id: scopeType === "team" ? assignmentForm.scope_id : null,
      project_id: scopeType === "project" ? assignmentForm.scope_id : null,
      allocation_id: scopeType === "allocation" ? assignmentForm.scope_id : null,
      virtual_key_id: scopeType === "virtual_key" ? assignmentForm.scope_id : null,
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
        description="Composable request policies that constrain models, providers, and pools."
        actions={
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
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        <SummaryCard label="Active policies" value={activePolicies.length} />
        <SummaryCard label="Enforced policies" value={enforcedPolicies.length} />
        <SummaryCard label="Recent blocks" value={blockedEvents.length} />
      </div>

      {policiesQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading guardrails...</p>
      ) : policies.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No guardrails yet"
          description="Create a policy to start constraining routing by model, provider, or pool."
          action={
            <Button onClick={openCreatePolicy}>
              <Plus data-icon="inline-start" />
              New policy
            </Button>
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
                  <TableHead className="w-24 text-right">Actions</TableHead>
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
                            onSelect={() => deletePolicy.mutate(policy.id)}
                            disabled={deletePolicy.isPending}
                          >
                            <Trash2 />
                            Delete policy
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
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
                    <TableHead>Status</TableHead>
                    <TableHead className="w-12">
                      <span className="sr-only">Actions</span>
                    </TableHead>
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
                        <StatusBadge variant={assignment.is_active ? "active" : "inactive"}>
                          {assignment.is_active ? "Active" : "Inactive"}
                        </StatusBadge>
                      </TableCell>
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
                              onSelect={() => deleteAssignment.mutate(assignment.id)}
                              disabled={deleteAssignment.isPending}
                            >
                              <Trash2 />
                              Remove assignment
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
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
              <Select value={eventDecision} onValueChange={setEventDecision}>
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All events</SelectItem>
                  <SelectItem value="allowed">Allowed</SelectItem>
                  <SelectItem value="warned">Warned</SelectItem>
                  <SelectItem value="blocked">Blocked</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            {filteredEvents.length === 0 ? (
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
                    <TableHead>Reason</TableHead>
                    <TableHead>Model</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredEvents.slice(0, 8).map((event) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <Badge variant={event.decision === "blocked" ? "destructive" : "outline"}>
                          {event.decision}
                        </Badge>
                      </TableCell>
                      <TableCell>{event.reason}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {event.requested_model ?? "-"}
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
                    Select the exact workspace object this policy should constrain.
                  </p>
                </div>
              ) : null}
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
          options={["model", "provider", "pool"]}
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
          placeholder="One model name or UUID per line"
          className="min-h-28 font-mono text-sm"
        />
      </Field>
    </div>
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
