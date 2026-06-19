import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { GuardrailPolicyResponse } from "@/shared/api/generated/schemas";

import { Field, SelectField } from "./GuardrailFormFields";
import {
  assignmentScopeTypes,
  matcherDimensionLabels,
  matcherDimensionOptions,
  matcherNeedsValue,
  matcherOperatorLabels,
  matcherOperatorOptions,
  newMatcherForm,
  newRuleForm,
  normalizeRulePhase,
  phaseOptionsForRuleType,
  ruleTypeLabels,
  ruleTypeOptions,
  ruleValuePlaceholder,
  type AssignmentFormState,
  type PolicyFormState,
  type PolicyRuleForm,
  type ScopeOptions,
  type ScopeType,
} from "../lib/guardrail-helpers";

export function GuardrailPolicySheet({
  open,
  onOpenChange,
  editingPolicy,
  form,
  setForm,
  assignmentForm,
  setAssignmentForm,
  assignmentScopeOptions,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingPolicy: GuardrailPolicyResponse | null;
  form: PolicyFormState;
  setForm: (form: PolicyFormState) => void;
  assignmentForm: AssignmentFormState;
  setAssignmentForm: (form: AssignmentFormState) => void;
  assignmentScopeOptions: ScopeOptions;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{editingPolicy ? "Edit policy" : "New policy"}</SheetTitle>
          <SheetDescription>
            Policies can include multiple rules. Any enabled rule that denies a request blocks it in
            enforce mode.
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
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
              </Field>
              <Field label="Description">
                <Textarea
                  value={form.description}
                  onChange={(event) => setForm({ ...form, description: event.target.value })}
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
                  checked={form.is_active}
                  onCheckedChange={(checked) => setForm({ ...form, is_active: checked })}
                />
              </div>
            </section>

            {!editingPolicy ? (
              <section className="grid gap-4">
                <div>
                  <h3 className="text-sm font-medium">Initial assignment</h3>
                  <p className="text-sm text-muted-foreground">
                    Assign this guardrail now, or leave it reusable and unassigned.
                  </p>
                </div>
                <SelectField
                  label="Scope"
                  value={assignmentForm.scope_type}
                  onValueChange={(value) =>
                    setAssignmentForm({ ...assignmentForm, scope_type: value, scope_id: "" })
                  }
                  options={["none", ...assignmentScopeTypes(assignmentScopeOptions)]}
                  labels={{
                    none: "Unassigned",
                    org: "Organization",
                    team: "Team",
                    project: "Project",
                    virtual_key: "Virtual key",
                  }}
                />
                {assignmentForm.scope_type !== "none" && assignmentForm.scope_type !== "org" ? (
                  <SelectField
                    label="Target"
                    value={assignmentForm.scope_id}
                    onValueChange={(value) =>
                      setAssignmentForm({ ...assignmentForm, scope_id: value })
                    }
                    options={assignmentScopeOptions[assignmentForm.scope_type as ScopeType].map(
                      (option) => option.id,
                    )}
                    labels={Object.fromEntries(
                      assignmentScopeOptions[assignmentForm.scope_type as ScopeType].map(
                        (option) => [option.id, option.label],
                      ),
                    )}
                    placeholder="Choose target"
                  />
                ) : null}
                {assignmentForm.scope_type !== "none" ? (
                  <SelectField
                    label="Assignment mode"
                    value={assignmentForm.enforcement_mode}
                    onValueChange={(value) =>
                      setAssignmentForm({ ...assignmentForm, enforcement_mode: value })
                    }
                    options={["enforce", "dry_run"]}
                    labels={{ enforce: "Enforce", dry_run: "Dry run / log only" }}
                  />
                ) : null}
              </section>
            ) : null}

            <section className="grid gap-4">
              <div>
                <h3 className="text-sm font-medium">Rules</h3>
                <p className="text-sm text-muted-foreground">
                  Allowlist rules define permitted sets. Deny rules block matching values. Rules are
                  evaluated in priority order.
                </p>
              </div>
              <SelectField
                label="Mode"
                value={form.enforcement_mode}
                onValueChange={(value) => setForm({ ...form, enforcement_mode: value })}
                options={["enforce", "monitor"]}
              />
              <div className="grid gap-3">
                {form.rules.map((rule, index) => (
                  <RuleEditor
                    key={rule.id}
                    rule={rule}
                    index={index}
                    canRemove={form.rules.length > 1}
                    onChange={(nextRule) =>
                      setForm({
                        ...form,
                        rules: form.rules.map((item) => (item.id === rule.id ? nextRule : item)),
                      })
                    }
                    onRemove={() =>
                      setForm({
                        ...form,
                        rules: form.rules.filter((item) => item.id !== rule.id),
                      })
                    }
                  />
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => setForm({ ...form, rules: [...form.rules, newRuleForm()] })}
              >
                <Plus data-icon="inline-start" />
                Add rule
              </Button>
            </section>
          </div>
        </div>
        <SheetFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isPending}>
            {editingPolicy ? "Save policy" : "Create policy"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
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
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_7rem]">
        <SelectField
          label="Rule"
          value={rule.rule_type}
          onValueChange={(value) =>
            onChange({ ...rule, rule_type: value, phase: normalizeRulePhase(value, rule.phase) })
          }
          options={ruleTypeOptions}
          labels={ruleTypeLabels}
        />
        <SelectField
          label="Effect"
          value={rule.effect}
          onValueChange={(value) => onChange({ ...rule, effect: value })}
          options={["allow", "deny"]}
          labels={{ allow: "Allowlist", deny: "Deny" }}
        />
        <SelectField
          label="Phase"
          value={rule.phase}
          onValueChange={(value) => onChange({ ...rule, phase: value })}
          options={phaseOptionsForRuleType(rule.rule_type)}
          labels={{ request: "Request", response: "Response", both: "Both" }}
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
      <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium">Applicability filters</div>
            <div className="text-xs text-muted-foreground">
              Leave filters empty to evaluate this rule on all assigned traffic.
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ ...rule, matchers: [...rule.matchers, newMatcherForm()] })}
          >
            <Plus data-icon="inline-start" />
            Add filter
          </Button>
        </div>
        {rule.matchers.length > 0 ? (
          <div className="grid gap-2">
            {rule.matchers.map((matcher) => (
              <div
                key={matcher.id}
                className="grid gap-2 rounded-md border bg-background p-2 sm:grid-cols-[1fr_9rem_1fr_auto]"
              >
                <SelectField
                  label="Dimension"
                  value={matcher.dimension}
                  onValueChange={(dimension) =>
                    onChange({
                      ...rule,
                      matchers: rule.matchers.map((item) =>
                        item.id === matcher.id ? { ...item, dimension } : item,
                      ),
                    })
                  }
                  options={matcherDimensionOptions}
                  labels={matcherDimensionLabels}
                />
                <SelectField
                  label="Operator"
                  value={matcher.operator}
                  onValueChange={(operator) =>
                    onChange({
                      ...rule,
                      matchers: rule.matchers.map((item) =>
                        item.id === matcher.id ? { ...item, operator } : item,
                      ),
                    })
                  }
                  options={matcherOperatorOptions}
                  labels={matcherOperatorLabels}
                />
                {matcherNeedsValue(matcher.operator) ? (
                  <Field label={matcher.operator === "in" ? "Values" : "Value"}>
                    <Input
                      value={matcher.value}
                      onChange={(event) =>
                        onChange({
                          ...rule,
                          matchers: rule.matchers.map((item) =>
                            item.id === matcher.id ? { ...item, value: event.target.value } : item,
                          ),
                        })
                      }
                      placeholder={matcher.operator === "in" ? "One value per line or comma" : ""}
                    />
                  </Field>
                ) : (
                  <div />
                )}
                <div className="flex items-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() =>
                      onChange({
                        ...rule,
                        matchers: rule.matchers.filter((item) => item.id !== matcher.id),
                      })
                    }
                    aria-label="Remove applicability filter"
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
