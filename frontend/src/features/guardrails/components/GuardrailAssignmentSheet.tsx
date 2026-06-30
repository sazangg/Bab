import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { GuardrailAssignmentResponse, GuardrailPolicyResponse } from "@/shared/api/generated/schemas";

import { SelectField } from "./GuardrailFormFields";
import {
  assignmentScopeTypes,
  type AssignmentFormState,
  type GuardrailPolicyOption,
  type GuardrailFormMetadata,
  type ScopeOptions,
  type ScopeType,
} from "../lib/guardrail-helpers";

export function GuardrailAssignmentSheet({
  open,
  onOpenChange,
  editingAssignment,
  form,
  setForm,
  policies,
  policyOptions,
  policyLabels,
  assignmentScopeOptions,
  scopeLabels,
  metadata,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingAssignment: GuardrailAssignmentResponse | null;
  form: AssignmentFormState;
  setForm: (form: AssignmentFormState) => void;
  policies: GuardrailPolicyResponse[];
  policyOptions: GuardrailPolicyOption[];
  policyLabels: Record<string, string>;
  assignmentScopeOptions: ScopeOptions;
  scopeLabels: Record<string, string>;
  metadata: GuardrailFormMetadata;
  onSubmit: () => void;
  isPending: boolean;
}) {
  const selectedPolicy = policies.find((policy) => policy.id === form.policy_id);
  const selectedPolicyOption = policyOptions.find((policy) => policy.id === form.policy_id);
  const selectedScopeOptions = assignmentScopeOptions[form.scope_type as ScopeType] ?? [];
  const selectedScope =
    form.scope_type === "none"
      ? "Unassigned"
      : form.scope_type === "org"
        ? "Organization"
        : scopeLabels[form.scope_id] || "No target selected";

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{editingAssignment ? "Edit assignment" : "Assign policy"}</SheetTitle>
          <SheetDescription>
            Assignments compose restrictively across org, team, project, and key.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="grid gap-4">
            <SelectField
              label="Policy"
              value={form.policy_id}
              onValueChange={(value) => setForm({ ...form, policy_id: value })}
              options={policyOptions
                .filter((policy) => policy.is_active || policy.id === form.policy_id)
                .map((policy) => policy.id)}
              labels={policyLabels}
            />
            <SelectField
              label="Scope"
              value={form.scope_type}
              onValueChange={(value) =>
                setForm({ ...form, scope_type: value as ScopeType, scope_id: "" })
              }
              options={assignmentScopeTypes(assignmentScopeOptions)}
            />
            {form.scope_type !== "none" && form.scope_type !== "org" ? (
              <div className="grid gap-2">
                <SelectField
                  label="Target"
                  value={form.scope_id}
                  onValueChange={(value) => setForm({ ...form, scope_id: value })}
                  options={selectedScopeOptions.map((option) => option.id)}
                  labels={Object.fromEntries(
                    selectedScopeOptions.map((option) => [option.id, option.label]),
                  )}
                  placeholder="Choose target"
                />
                <p className="text-xs text-muted-foreground">
                  {selectedScopeOptions.length === 0
                    ? `No ${form.scope_type.replace("_", " ")} targets are available yet.`
                    : "Select the exact workspace object this policy should constrain."}
                </p>
              </div>
            ) : null}
            <SelectField
              label="Mode"
              value={form.enforcement_mode}
              onValueChange={(value) => setForm({ ...form, enforcement_mode: value })}
              options={metadata.assignmentEnforcementModes}
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
                    {selectedPolicyOption?.name ?? "No policy selected"}
                  </span>
                </div>
                <div>
                  Scope: <span className="text-foreground">{selectedScope}</span>
                </div>
                <div>
                  Rules:{" "}
                  <span className="text-foreground">
                    {selectedPolicy
                      ? `${selectedPolicy.rules.filter((rule) => rule.is_active).length} active`
                      : selectedPolicyOption
                        ? "Managed by organization admin"
                        : "-"}
                  </span>
                </div>
                <div>
                  Mode:{" "}
                  <span className="text-foreground">
                    {form.enforcement_mode === "dry_run" ? "Dry run" : "Enforce"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <SheetFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isPending}>
            {editingAssignment ? "Save assignment" : "Assign policy"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
