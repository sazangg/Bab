import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Gauge, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  useCreateLimitPolicyApiV1LimitPoliciesPost,
  useDeactivateLimitPolicyApiV1LimitPoliciesPolicyIdDelete,
  useListLimitPoliciesApiV1LimitPoliciesGet,
} from "@/shared/api/generated/limit-policies/limit-policies";
import type { ProviderResponse, VirtualKeyResponse } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";

const scopeOptions = [
  { value: "project", label: "This project" },
  { value: "virtual_key", label: "Specific key" },
  { value: "provider", label: "Provider" },
  { value: "provider_model", label: "Provider model" },
] as const;

const metricOptions = [
  { value: "request_count", label: "Requests" },
  { value: "token_count", label: "Tokens" },
] as const;

const windowOptions = [
  { value: "minute", label: "Per minute" },
  { value: "day", label: "Per day" },
  { value: "total", label: "Total" },
] as const;

const limitSchema = z.object({
  scope_type: z.enum(["project", "virtual_key", "provider", "provider_model"]),
  scope_id: z.string().min(1),
  scope_value: z.string().optional(),
  metric: z.enum(["request_count", "token_count"]),
  window: z.enum(["minute", "day", "total"]),
  limit_value: z.coerce.number().int().positive(),
});

type LimitValues = z.input<typeof limitSchema>;
type LimitOutput = z.output<typeof limitSchema>;

export function ProjectLimitsSection({
  projectId,
  keys,
  providers,
}: {
  projectId: string;
  keys: VirtualKeyResponse[];
  providers: ProviderResponse[];
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const policiesQuery = useListLimitPoliciesApiV1LimitPoliciesGet();

  const projectKeyIds = useMemo(() => new Set(keys.map((k) => k.id)), [keys]);
  const policies = useMemo(() => {
    const allPolicies = policiesQuery.data?.status === 200 ? policiesQuery.data.data : [];
    return allPolicies.filter((policy) => {
      if (policy.scope_type === "project" && policy.scope_id === projectId) return true;
      if (policy.scope_type === "virtual_key" && projectKeyIds.has(policy.scope_id ?? ""))
        return true;
      return false;
    });
  }, [policiesQuery.data, projectId, projectKeyIds]);

  const form = useForm<LimitValues, unknown, LimitOutput>({
    resolver: zodResolver(limitSchema),
    defaultValues: {
      scope_type: "project",
      scope_id: projectId,
      scope_value: "",
      metric: "request_count",
      window: "minute",
      limit_value: 60,
    },
  });

  const createMutation = useCreateLimitPolicyApiV1LimitPoliciesPost({
    mutation: {
      onSuccess: async () => {
        form.reset({
          scope_type: "project",
          scope_id: projectId,
          scope_value: "",
          metric: "request_count",
          window: "minute",
          limit_value: 60,
        });
        setOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateMutation = useDeactivateLimitPolicyApiV1LimitPoliciesPolicyIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
    },
  });

  const scopeType = useWatch({ control: form.control, name: "scope_type" });
  const scopeId = useWatch({ control: form.control, name: "scope_id" });
  const metric = useWatch({ control: form.control, name: "metric" });
  const windowValue = useWatch({ control: form.control, name: "window" });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Limits</CardTitle>
            <CardDescription>
              Caps applied to this project or its keys. Hits return 429.
            </CardDescription>
          </div>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button size="sm">
                <Plus />
                New limit
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>New limit policy</SheetTitle>
                <SheetDescription>Pick what to limit, then how much.</SheetDescription>
              </SheetHeader>
              <form
                className="grid gap-4 px-4"
                onSubmit={form.handleSubmit((values) => createMutation.mutate({ data: values }))}
              >
                <div className="space-y-1.5">
                  <Label>Scope</Label>
                  <Select
                    value={scopeType}
                    onValueChange={(value) => {
                      form.setValue("scope_type", value as LimitValues["scope_type"]);
                      if (value === "project") form.setValue("scope_id", projectId);
                      else form.setValue("scope_id", "");
                      form.setValue("scope_value", "");
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {scopeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {scopeType === "virtual_key" ? (
                  <div className="space-y-1.5">
                    <Label>Key</Label>
                    <Select
                      value={scopeId}
                      onValueChange={(value) => form.setValue("scope_id", value)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select key" />
                      </SelectTrigger>
                      <SelectContent>
                        {keys.map((key) => (
                          <SelectItem key={key.id} value={key.id}>
                            {key.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}

                {scopeType === "provider" || scopeType === "provider_model" ? (
                  <div className="space-y-1.5">
                    <Label>Provider</Label>
                    <Select
                      value={scopeId}
                      onValueChange={(value) => form.setValue("scope_id", value)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select provider" />
                      </SelectTrigger>
                      <SelectContent>
                        {providers.map((provider) => (
                          <SelectItem key={provider.id} value={provider.id}>
                            {provider.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}

                {scopeType === "provider_model" ? (
                  <div className="space-y-1.5">
                    <Label htmlFor="limit-model">Provider model</Label>
                    <Input
                      id="limit-model"
                      placeholder="gpt-4o"
                      {...form.register("scope_value")}
                    />
                  </div>
                ) : null}

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label>Metric</Label>
                    <Select
                      value={metric}
                      onValueChange={(value) =>
                        form.setValue("metric", value as "request_count" | "token_count")
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {metricOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Window</Label>
                    <Select
                      value={windowValue}
                      onValueChange={(value) =>
                        form.setValue("window", value as "minute" | "day" | "total")
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {windowOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="limit-value">Threshold</Label>
                  <Input id="limit-value" type="number" min={1} {...form.register("limit_value")} />
                </div>
              </form>
              <SheetFooter>
                <Button
                  type="submit"
                  disabled={createMutation.isPending}
                  onClick={form.handleSubmit((values) => createMutation.mutate({ data: values }))}
                >
                  {createMutation.isPending ? "Saving..." : "Create limit"}
                </Button>
                <SheetClose asChild>
                  <Button variant="outline">Cancel</Button>
                </SheetClose>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </div>
      </CardHeader>
      <CardContent>
        {policiesQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading limits...</p>
        ) : policies.length === 0 ? (
          <EmptyState
            icon={Gauge}
            title="No limits configured"
            description="Add a limit to cap requests or tokens for this project."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scope</TableHead>
                <TableHead>Metric</TableHead>
                <TableHead>Window</TableHead>
                <TableHead className="text-right">Threshold</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy) => (
                <TableRow key={policy.id}>
                  <TableCell>
                    {policy.scope_type === "project"
                      ? "Project"
                      : policy.scope_type === "virtual_key"
                        ? `Key: ${
                            keys.find((k) => k.id === policy.scope_id)?.name ?? policy.scope_id
                          }`
                        : policy.scope_type === "provider"
                          ? `Provider: ${
                              providers.find((p) => p.id === policy.scope_id)?.name ??
                              policy.scope_id
                            }`
                          : `Model: ${policy.scope_value ?? "—"}`}
                  </TableCell>
                  <TableCell>{policy.metric === "request_count" ? "Requests" : "Tokens"}</TableCell>
                  <TableCell className="capitalize">{policy.window}</TableCell>
                  <TableCell className="text-right tabular-nums">{policy.limit_value}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove limit"
                      disabled={deactivateMutation.isPending}
                      onClick={() => deactivateMutation.mutate({ policyId: policy.id })}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
