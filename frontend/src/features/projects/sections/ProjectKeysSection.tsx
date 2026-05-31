import { zodResolver } from "@hookform/resolvers/zod";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import {
  useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost,
  getVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet,
  useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
} from "@/shared/api/generated/projects/projects";
import { useListTeamAllocationsApiV1TeamsTeamIdAllocationsGet } from "@/shared/api/generated/teams/teams";
import type {
  CreatedVirtualKeyResponse,
  ModelOfferingResponse,
  ProjectResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { StatusBadge } from "@/shared/components/StatusBadge";
import {
  listModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";

const keySchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
  allocation_id: z.string().optional(),
  allowed_models: z.string().optional(),
  max_requests_per_minute: z.string().optional(),
  max_tokens_per_minute: z.string().optional(),
  max_tokens_per_request: z.string().optional(),
});

type KeyValues = z.infer<typeof keySchema>;

export function ProjectKeysSection({
  projectId,
  project,
  keys,
  isLoading,
  onView,
  canManage,
}: {
  projectId: string;
  project: ProjectResponse;
  keys: VirtualKeyResponse[];
  isLoading: boolean;
  onView: (keyId: string) => void;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<CreatedVirtualKeyResponse | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const form = useForm<KeyValues>({
    resolver: zodResolver(keySchema),
    defaultValues: {
      name: "",
      expires_at: "",
      allocation_id: "inherited",
      allowed_models: "",
      max_requests_per_minute: "",
      max_tokens_per_minute: "",
      max_tokens_per_request: "",
    },
  });
  const selectedAllocationId = useWatch({ control: form.control, name: "allocation_id" });
  const allowedModelsValue = useWatch({ control: form.control, name: "allowed_models" });
  const allocationsQuery = useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet(
    projectId,
    { query: { enabled: Boolean(projectId) } },
  );
  const teamAllocationsQuery = useListTeamAllocationsApiV1TeamsTeamIdAllocationsGet(
    project.team_id,
    { query: { enabled: Boolean(project.team_id) } },
  );
  const allocations = allocationsQuery.data?.status === 200 ? allocationsQuery.data.data : [];
  const teamAllocations =
    teamAllocationsQuery.data?.status === 200 ? teamAllocationsQuery.data.data : [];
  const visibleAllocations = [...allocations, ...teamAllocations];
  const customAllocations = allocations.filter((allocation) => allocation.is_active);
  const effectiveAllocation =
    allocations.find((allocation) => allocation.is_default && allocation.is_active) ??
    teamAllocations.find((allocation) => allocation.is_default && allocation.is_active);
  const selectedAllocation =
    selectedAllocationId && selectedAllocationId !== "inherited"
      ? customAllocations.find((allocation) => allocation.id === selectedAllocationId)
      : effectiveAllocation;
  const selectedAllowedModels = parseModels(allowedModelsValue) ?? [];
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const modelQueries = useQueries({
    queries: providers.map((provider) => ({
      queryKey: ["project-key-models", provider.id],
      queryFn: () =>
        listModelOfferingsApiV1ProvidersProviderIdOfferingsGet(provider.id, { limit: 100 }),
      enabled: createOpen,
    })),
  });
  const modelOfferings = modelQueries.flatMap((query) =>
    query.data?.status === 200 ? query.data.data.items : [],
  );
  const modelById = new Map(modelOfferings.map((model) => [model.id, model]));
  const selectableModels =
    selectedAllocation?.offerings
      .map((offering) => modelById.get(offering.model_offering_id))
      .filter((model): model is ModelOfferingResponse => Boolean(model?.is_active)) ?? [];
  const keyUsageQueries = useQueries({
    queries: keys.map((key) => ({
      queryKey: ["project-key-usage", projectId, key.id],
      queryFn: () => getVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet(projectId, key.id),
      enabled: Boolean(projectId && key.id),
    })),
  });

  const createMutation = useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          setCreatedKey(response.data);
          form.reset({
            name: "",
            expires_at: "",
            allocation_id: "inherited",
            allowed_models: "",
            max_requests_per_minute: "",
            max_tokens_per_minute: "",
            max_tokens_per_request: "",
          });
          setCreateOpen(false);
          await queryClient.invalidateQueries();
        }
      },
    },
  });
  const revokeMutation = useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete({
    mutation: {
      onSuccess: async () => {
        setRevokeId(null);
        await queryClient.invalidateQueries();
      },
    },
  });

  const submit = (values: KeyValues) =>
    createMutation.mutate({
      projectId,
      data: {
        name: values.name,
        expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
        allocation_id: values.allocation_id === "inherited" ? null : values.allocation_id,
        allowed_models: parseModels(values.allowed_models),
        max_requests_per_minute: parseOptionalNumber(values.max_requests_per_minute),
        max_tokens_per_minute: parseOptionalNumber(values.max_tokens_per_minute),
        max_tokens_per_request: parseOptionalNumber(values.max_tokens_per_request),
      },
    });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Virtual keys</CardTitle>
          <CardDescription>
            Each key uses the current project default, or the current team default when the project
            has none. Custom overrides can only use active allocations from this project.
          </CardDescription>
          {canManage ? (
            <CardAction>
              <Sheet open={createOpen} onOpenChange={setCreateOpen}>
                <SheetTrigger asChild>
                  <Button size="sm" disabled={!project.is_active || !effectiveAllocation}>
                    <Plus />
                    New key
                  </Button>
                </SheetTrigger>
                <SheetContent>
                  <SheetHeader>
                    <SheetTitle>New virtual key</SheetTitle>
                    <SheetDescription>
                      {effectiveAllocation
                        ? `Uses current default: ${effectiveAllocation.name} unless a project allocation override is selected.`
                        : "Create a team or project allocation before issuing a key."}
                    </SheetDescription>
                  </SheetHeader>
                  <form
                    className="grid gap-4 overflow-y-auto px-6 py-5"
                    onSubmit={form.handleSubmit(submit)}
                  >
                    <div className="space-y-1.5">
                      <Label htmlFor="key-name">Label</Label>
                      <Input id="key-name" autoFocus {...form.register("name")} />
                      {form.formState.errors.name ? (
                        <p className="text-xs text-destructive">
                          {form.formState.errors.name.message}
                        </p>
                      ) : null}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="key-expires">Expires at</Label>
                      <Input
                        id="key-expires"
                        type="datetime-local"
                        {...form.register("expires_at")}
                      />
                      <p className="text-xs text-muted-foreground">
                        Optional. Blank uses the organization default if configured.
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <Label>Allocation</Label>
                      <Select
                        value={selectedAllocationId}
                        onValueChange={(value) =>
                          form.setValue("allocation_id", value, { shouldDirty: true })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="inherited">
                            Use current project/team default ({effectiveAllocation?.name ?? "none"})
                          </SelectItem>
                          {customAllocations.map((allocation) => (
                            <SelectItem key={allocation.id} value={allocation.id}>
                              {allocation.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="rounded-md border bg-muted/30 p-3 text-sm">
                      <span className="text-xs text-muted-foreground">Effective allocation</span>
                      <p className="font-medium">{selectedAllocation?.name ?? "None configured"}</p>
                    </div>
                    <div className="space-y-2">
                      <div>
                        <Label>Allowed models</Label>
                        <p className="text-xs text-muted-foreground">
                          Optional subset of the selected allocation. Leave blank to allow every
                          allocation model.
                        </p>
                      </div>
                      <div className="rounded-md border">
                        <ScrollArea className="h-60">
                          <div className="grid gap-1 p-2">
                            {!selectedAllocation ? (
                              <p className="p-2 text-sm text-muted-foreground">
                                Select an allocation to choose models.
                              </p>
                            ) : selectableModels.length === 0 ? (
                              <p className="p-2 text-sm text-muted-foreground">
                                No active models are available for this allocation.
                              </p>
                            ) : (
                              selectableModels.map((model) => {
                                const checked = selectedAllowedModels.includes(
                                  model.provider_model_name,
                                );
                                return (
                                  <label
                                    key={model.id}
                                    className="flex min-w-0 cursor-pointer items-start gap-3 rounded-md px-2 py-2 hover:bg-muted/50"
                                  >
                                    <Checkbox
                                      checked={checked}
                                      onCheckedChange={(nextChecked) => {
                                        const nextModels = nextChecked
                                          ? [...selectedAllowedModels, model.provider_model_name]
                                          : selectedAllowedModels.filter(
                                              (name) => name !== model.provider_model_name,
                                            );
                                        form.setValue("allowed_models", nextModels.join(", "), {
                                          shouldDirty: true,
                                        });
                                      }}
                                    />
                                    <span className="min-w-0">
                                      <span className="block text-sm font-medium break-words">
                                        {model.alias || model.provider_model_name}
                                      </span>
                                      <span className="block text-xs break-all text-muted-foreground">
                                        {model.provider_model_name}
                                      </span>
                                    </span>
                                  </label>
                                );
                              })
                            )}
                          </div>
                        </ScrollArea>
                      </div>
                      {selectedAllowedModels.length > 0 ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="w-fit"
                          onClick={() => form.setValue("allowed_models", "", { shouldDirty: true })}
                        >
                          Allow all allocation models
                        </Button>
                      ) : null}
                    </div>
                    <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
                      <div>
                        <Label>Key-level limits</Label>
                        <p className="text-xs text-muted-foreground">
                          Optional caps applied directly to this key before allocation windows.
                        </p>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-3">
                        <LimitInput
                          id="key-max-requests-minute"
                          label="Requests/min"
                          registration={form.register("max_requests_per_minute")}
                        />
                        <LimitInput
                          id="key-max-tokens-minute"
                          label="Tokens/min"
                          registration={form.register("max_tokens_per_minute")}
                        />
                        <LimitInput
                          id="key-max-tokens-request"
                          label="Tokens/request"
                          registration={form.register("max_tokens_per_request")}
                        />
                      </div>
                    </div>
                  </form>
                  <SheetFooter>
                    <Button
                      type="submit"
                      disabled={createMutation.isPending || !effectiveAllocation}
                      onClick={form.handleSubmit(submit)}
                    >
                      {createMutation.isPending ? "Creating..." : "Create key"}
                    </Button>
                    <SheetClose asChild>
                      <Button variant="outline">Cancel</Button>
                    </SheetClose>
                  </SheetFooter>
                </SheetContent>
              </Sheet>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading keys...</p>
          ) : keys.length === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No virtual keys yet"
              description="Create a key to issue this project's first credential."
            />
          ) : (
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Prefix</TableHead>
                    <TableHead>Allocation</TableHead>
                    <TableHead>Usage</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-[1%]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map((key, index) => {
                    const usageResponse = keyUsageQueries[index]?.data;
                    const usage = usageResponse?.status === 200 ? usageResponse.data : undefined;
                    return (
                      <TableRow
                        key={key.id}
                        className="cursor-pointer"
                        onClick={() => onView(key.id)}
                      >
                        <TableCell className="font-medium">{key.name}</TableCell>
                        <TableCell className="font-mono text-xs">{key.key_prefix}</TableCell>
                        <TableCell className="text-muted-foreground">
                          <div className="flex flex-col gap-1">
                            <span>
                              {visibleAllocations.find(
                                (allocation) => allocation.id === key.allocation_id,
                              )?.name ?? key.allocation_id}
                            </span>
                            <span className="text-xs">
                              {key.allocation_mode === "custom"
                                ? "Custom project override"
                                : "Current default"}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          <KeyUsageInline
                            requests={usage?.totals.requests ?? 0}
                            tokens={usage?.totals.total_tokens ?? 0}
                            errors={usage?.totals.failed_requests ?? 0}
                          />
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : "Never"}
                        </TableCell>
                        <TableCell>
                          <KeyStatusBadge virtualKey={key} />
                        </TableCell>
                        <TableCell
                          className="text-right"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {canManage ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={Boolean(key.revoked_at)}
                              onClick={() => setRevokeId(key.id)}
                            >
                              Revoke
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(createdKey)}
        onOpenChange={(open) => {
          if (!open) {
            setCreatedKey(null);
            setCopied(false);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Key created</DialogTitle>
            <DialogDescription>
              {createdKey?.key
                ? "Copy the key now. It cannot be displayed again."
                : "Secret copy is disabled in settings, so the plaintext key was not returned."}
            </DialogDescription>
          </DialogHeader>
          {createdKey?.key ? (
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
              <code className="min-w-0 flex-1 overflow-auto text-xs">{createdKey.key}</code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  navigator.clipboard.writeText(createdKey.key ?? "");
                  setCopied(true);
                }}
              >
                {copied ? <Check /> : <Copy />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          ) : (
            <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
              Key prefix:{" "}
              <span className="font-mono text-foreground">{createdKey?.key_prefix}</span>
            </div>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button>Done</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(revokeId)} onOpenChange={(open) => !open && setRevokeId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this key?</DialogTitle>
            <DialogDescription>
              The key will stop authenticating immediately. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={revokeMutation.isPending}
              onClick={() => revokeId && revokeMutation.mutate({ projectId, keyId: revokeId })}
            >
              {revokeMutation.isPending ? "Revoking..." : "Revoke key"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function KeyStatusBadge({ virtualKey }: { virtualKey: VirtualKeyResponse }) {
  if (virtualKey.revoked_at) {
    return <StatusBadge variant="revoked">Revoked</StatusBadge>;
  }
  if (virtualKey.expires_at && new Date(virtualKey.expires_at) < new Date()) {
    return <StatusBadge variant="expired">Expired</StatusBadge>;
  }
  return <StatusBadge variant="active">Active</StatusBadge>;
}

function KeyUsageInline({
  requests,
  tokens,
  errors,
}: {
  requests: number;
  tokens: number;
  errors: number;
}) {
  const hasUsage = requests > 0;
  return (
    <div className="flex flex-col gap-1 text-xs">
      <span className="font-medium text-foreground">
        {hasUsage ? `${requests.toLocaleString()} req` : "No usage"}
      </span>
      <span>
        {tokens.toLocaleString()} tok
        {errors > 0 ? ` · ${errors.toLocaleString()} err` : ""}
      </span>
    </div>
  );
}

function LimitInput({
  id,
  label,
  registration,
}: {
  id: string;
  label: string;
  registration: UseFormRegisterReturn;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" min={1} inputMode="numeric" {...registration} />
    </div>
  );
}

function parseOptionalNumber(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  return Number(value);
}

function parseModels(value: string | undefined): string[] | null {
  const models = value
    ?.split(",")
    .map((m) => m.trim())
    .filter(Boolean);
  return models && models.length > 0 ? models : null;
}
