import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronDown,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useQueryState } from "nuqs";
import { useEffect, useState } from "react";
import { useForm, useWatch, type UseFormRegister } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  useDeleteCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdDelete,
  useAddCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPost,
  useCreateCredentialPoolApiV1ProvidersProviderIdPoolsPost,
  useCreateModelOfferingApiV1ProvidersProviderIdOfferingsPost,
  useCreateProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useDeactivateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdDelete,
  useDeactivateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdDelete,
  useListCredentialPoolCredentialsApiV1ProvidersProviderIdPoolsPoolIdCredentialsGet,
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet,
  useSyncModelOfferingsApiV1ProvidersProviderIdOfferingsSyncPost,
  useTestModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdTestPost,
  useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost,
  useUpdateCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdPatch,
  useUpdateCredentialPoolApiV1ProvidersProviderIdPoolsPoolIdPatch,
  useUpdateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdPatch,
  useUpdateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdPatch,
} from "@/shared/api/generated/providers/providers";
import type {
  CredentialPoolCredentialResponse,
  CredentialPoolResponse,
  ModelOfferingResponse,
  ProviderCredentialResponse,
  ProviderResponse,
} from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import {
  capabilityListToRecord,
  capabilityRecordToList,
  combinedModality,
  formatDateTime,
  formatModalities,
  formatRelativeFromNow,
  formatTokenPrice,
  sanitizeCredentialValidationMessage,
} from "../lib/format";
import {
  modelCapabilityOptions,
  modelModalities,
  modelOfferingSchema,
  credentialPoolSchema,
  providerCredentialSchema,
  routingPolicyOptions,
  type CredentialPoolValues,
  type ModelOfferingFormInput,
  type ModelOfferingValues,
  type ProviderCredentialValues,
} from "../lib/schemas";

export function ProviderResourcesPanel({ provider }: { provider: ProviderResponse }) {
  return <ProviderResourcesContent provider={provider} />;
}

function ProviderResourcesContent({ provider }: { provider: ProviderResponse }) {
  const queryClient = useQueryClient();
  const providerId = provider.id;
  const [tab, setTab] = useQueryState("tab", { defaultValue: "credentials" });
  const activeTab = tab === "models" || tab === "pools" ? tab : "credentials";
  const [modelSearch, setModelSearch] = useQueryState("modelSearch", { defaultValue: "" });
  const [modelModality, setModelModality] = useQueryState("modality", { defaultValue: "all" });
  const [modelStatus, setModelStatus] = useQueryState("modelStatus", { defaultValue: "all" });
  const [modelPageParam, setModelPageParam] = useQueryState("modelPage", { defaultValue: "1" });
  const modelPageSize = 24;
  const modelPage = Math.max(Number(modelPageParam) || 1, 1);
  const modelOffset = (modelPage - 1) * modelPageSize;
  const modelParams = {
    search: modelSearch.trim() || undefined,
    modality: modelModality === "all" ? undefined : modelModality,
    is_active: modelStatus === "all" ? undefined : modelStatus === "active" ? true : false,
    limit: modelPageSize,
    offset: modelOffset,
  };
  const [createCredentialOpen, setCreateCredentialOpen] = useState(false);
  const [createPoolOpen, setCreatePoolOpen] = useState(false);
  const [createModelOpen, setCreateModelOpen] = useState(false);
  const [selectedPoolId, setSelectedPoolId] = useState<string | null>(null);
  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    providerId,
    {
      query: { enabled: Boolean(providerId) },
    },
  );
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(
    providerId,
    modelParams,
    {
      query: { enabled: Boolean(providerId) },
    },
  );
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const selectedPool = pools.find((pool) => pool.id === selectedPoolId) ?? pools[0] ?? null;
  const effectiveSelectedPoolId = selectedPool?.id ?? "";
  const poolCredentialsQuery =
    useListCredentialPoolCredentialsApiV1ProvidersProviderIdPoolsPoolIdCredentialsGet(
      providerId,
      effectiveSelectedPoolId,
      { query: { enabled: Boolean(providerId && effectiveSelectedPoolId) } },
    );
  const poolCredentials =
    poolCredentialsQuery.data?.status === 200 ? poolCredentialsQuery.data.data : [];
  const modelsPage =
    modelsQuery.data?.status === 200
      ? modelsQuery.data.data
      : { items: [], total: 0, limit: modelPageSize, offset: modelOffset };

  const createPool = useCreateCredentialPoolApiV1ProvidersProviderIdPoolsPost({
    mutation: {
      onSuccess: async () => {
        setCreatePoolOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updatePool = useUpdateCredentialPoolApiV1ProvidersProviderIdPoolsPoolIdPatch({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const addPoolCredential =
    useAddCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPost({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const updatePoolCredential =
    useUpdateCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdPatch(
      {
        mutation: { onSuccess: async () => queryClient.invalidateQueries() },
      },
    );
  const deletePoolCredential =
    useDeleteCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdDelete(
      {
        mutation: { onSuccess: async () => queryClient.invalidateQueries() },
      },
    );
  const createCredential = useCreateProviderCredentialApiV1ProvidersProviderIdCredentialsPost({
    mutation: {
      onSuccess: async () => {
        setCreateCredentialOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateCredential =
    useUpdateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdPatch({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const deactivateCredential =
    useDeactivateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdDelete({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const createModel = useCreateModelOfferingApiV1ProvidersProviderIdOfferingsPost({
    mutation: {
      onSuccess: async () => {
        setCreateModelOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateModel = useUpdateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdPatch({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const deactivateModel =
    useDeactivateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdDelete({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const syncModels = useSyncModelOfferingsApiV1ProvidersProviderIdOfferingsSyncPost({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const testCredential =
    useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost({
      mutation: { onSettled: async () => queryClient.invalidateQueries() },
    });
  const testModel = useTestModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdTestPost({
    mutation: { onSettled: async () => queryClient.invalidateQueries() },
  });
  const hasActiveCredential = credentials.some((credential) => credential.is_active);
  const [bulkTestProgress, setBulkTestProgress] = useState<{
    index: number;
    total: number;
  } | null>(null);

  async function handleTestAllCredentials() {
    const active = credentials.filter((credential) => credential.is_active);
    if (active.length === 0) return;
    let passed = 0;
    let failed = 0;
    for (let i = 0; i < active.length; i++) {
      const credential = active[i];
      setBulkTestProgress({ index: i + 1, total: active.length });
      try {
        const response = await testCredential.mutateAsync({
          providerId,
          providerCredentialId: credential.id,
        });
        if (response.status === 200 && response.data.health_status === "valid") {
          passed++;
        } else {
          failed++;
        }
      } catch {
        failed++;
      }
    }
    setBulkTestProgress(null);
    if (failed === 0) {
      toast.success(`All ${passed} credential${passed === 1 ? "" : "s"} passed.`);
    } else {
      toast.error(`${failed} of ${active.length} credentials failed. ${passed} passed.`);
    }
  }

  function handleTestCredential(providerCredential: ProviderCredentialResponse) {
    testCredential.mutate(
      { providerId, providerCredentialId: providerCredential.id },
      {
        onSuccess: (response) => {
          if (response.status !== 200) {
            toast.error(
              `${providerCredential.name}: credential validation failed. Check the key and provider settings.`,
            );
            return;
          }

          if (response.data.health_status === "valid") {
            toast.success(`${providerCredential.name}: credential test succeeded.`);
          } else {
            const message =
              sanitizeCredentialValidationMessage(response.data.last_validation_error) ??
              "Credential test failed.";
            toast.error(`${providerCredential.name}: ${message}`);
          }
        },
        onError: () => {
          toast.error(
            `${providerCredential.name}: credential validation failed. Check the key and provider settings.`,
          );
        },
      },
    );
  }

  function handleTestModel(model: ModelOfferingResponse) {
    testModel.mutate(
      { providerId, modelOfferingId: model.id },
      {
        onSuccess: (response) => {
          if (response.status !== 200) {
            toast.error(
              `${model.provider_model_name}: model validation failed. Check the model and provider credentials.`,
            );
            return;
          }

          if (response.data.health_status === "valid") {
            toast.success(`${model.provider_model_name}: model test succeeded.`);
          } else {
            const message =
              sanitizeCredentialValidationMessage(response.data.last_validation_error) ??
              "Model test failed.";
            toast.error(`${model.provider_model_name}: ${message}`);
          }
        },
        onError: () => {
          toast.error(
            `${model.provider_model_name}: model validation failed. Check the model and provider credentials.`,
          );
        },
      },
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Provider resources</CardTitle>
          <CardDescription>
            Pools group credentials for allocations. Models define what this provider can serve.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setTab} className="gap-5">
            <TabsList>
              <TabsTrigger value="credentials">Credentials</TabsTrigger>
              <TabsTrigger value="pools">Pools</TabsTrigger>
              <TabsTrigger value="models">Models</TabsTrigger>
            </TabsList>
            <TabsContent value="credentials" className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Credentials</h3>
                  <p className="text-sm text-muted-foreground">
                    Credentials are encrypted and selected through credential pools.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={bulkTestProgress !== null || !credentials.some((c) => c.is_active)}
                    onClick={handleTestAllCredentials}
                    title={
                      credentials.some((c) => c.is_active)
                        ? "Test every active credential, one after another."
                        : "Add an active credential first."
                    }
                  >
                    <Activity />
                    {bulkTestProgress
                      ? `Testing ${bulkTestProgress.index}/${bulkTestProgress.total}…`
                      : "Test all"}
                  </Button>
                  <Button size="sm" onClick={() => setCreateCredentialOpen(true)}>
                    <Plus />
                    Add credential
                  </Button>
                </div>
              </div>
              <ResourceKeyTable
                providerId={providerId}
                credentials={credentials}
                isLoading={credentialsQuery.isPending || credentialsQuery.isFetching}
                isError={credentialsQuery.isError}
                isTesting={testCredential.isPending}
                onUpdate={(credential, values) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: {
                      name: values.name,
                    },
                  })
                }
                onRotate={(credential, apiKey) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: { api_key: apiKey },
                  })
                }
                onDeactivate={(credential) =>
                  deactivateCredential.mutate({ providerId, providerCredentialId: credential.id })
                }
                onReactivate={(credential) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: { is_active: true },
                  })
                }
                onTest={handleTestCredential}
              />
            </TabsContent>

            <TabsContent value="pools" className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Credential pools</h3>
                  <p className="text-sm text-muted-foreground">
                    Pools are the routing resources allocations point to.
                  </p>
                </div>
                <Button size="sm" onClick={() => setCreatePoolOpen(true)}>
                  <Plus />
                  New pool
                </Button>
              </div>
              <CredentialPoolTable
                pools={pools}
                selectedPoolId={selectedPool?.id ?? null}
                isLoading={poolsQuery.isPending || poolsQuery.isFetching}
                isError={poolsQuery.isError}
                onSelect={setSelectedPoolId}
                onUpdate={(pool, values) =>
                  updatePool.mutate({
                    providerId,
                    poolId: pool.id,
                    data: {
                      name: values.name,
                      description: values.description?.trim() ? values.description : null,
                      selection_policy: values.selection_policy,
                    },
                  })
                }
                onDeactivate={(pool) =>
                  updatePool.mutate({
                    providerId,
                    poolId: pool.id,
                    data: { is_active: false },
                  })
                }
                onReactivate={(pool) =>
                  updatePool.mutate({
                    providerId,
                    poolId: pool.id,
                    data: { is_active: true },
                  })
                }
              />
              <CredentialPoolMembersPanel
                providerId={providerId}
                pool={selectedPool}
                credentials={credentials}
                members={poolCredentials}
                isLoading={poolCredentialsQuery.isPending || poolCredentialsQuery.isFetching}
                isError={poolCredentialsQuery.isError}
                isAdding={addPoolCredential.isPending}
                onAdd={(pool, values) =>
                  addPoolCredential.mutate({
                    providerId,
                    poolId: pool.id,
                    data: values,
                  })
                }
                onUpdate={(pool, member, values) =>
                  updatePoolCredential.mutate({
                    providerId,
                    poolId: pool.id,
                    poolCredentialId: member.id,
                    data: values,
                  })
                }
                onDelete={(pool, member) =>
                  deletePoolCredential.mutate({
                    providerId,
                    poolId: pool.id,
                    poolCredentialId: member.id,
                  })
                }
              />
            </TabsContent>

            <TabsContent value="models" className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Models</h3>
                  <p className="text-sm text-muted-foreground">
                    Alias is optional and scoped to this provider.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => setCreateModelOpen(true)}>
                    <Plus />
                    Add model
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!providerId || !hasActiveCredential || syncModels.isPending}
                        title={
                          !hasActiveCredential
                            ? "Add an active credential before syncing models."
                            : undefined
                        }
                      >
                        <RefreshCw />
                        Sync
                        <ChevronDown />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-72">
                      <DropdownMenuLabel>Sync models</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={() =>
                          providerId &&
                          syncModels.mutate({
                            providerId,
                            data: { metadata_mode: "fill_missing" },
                          })
                        }
                      >
                        Fill missing metadata
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() =>
                          providerId &&
                          syncModels.mutate({
                            providerId,
                            data: { metadata_mode: "overwrite_catalog" },
                          })
                        }
                      >
                        Overwrite with catalog metadata
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
              <ResourceModelTable
                providerId={providerId}
                models={modelsPage.items}
                total={modelsPage.total}
                limit={modelsPage.limit}
                offset={modelsPage.offset}
                search={modelSearch}
                modality={modelModality}
                status={modelStatus}
                page={modelPage}
                isLoading={modelsQuery.isPending || modelsQuery.isFetching}
                isError={modelsQuery.isError}
                hasActiveCredential={hasActiveCredential}
                isTesting={testModel.isPending}
                onSearchChange={(value) => {
                  void setModelSearch(value);
                  void setModelPageParam("1");
                }}
                onModalityChange={(value) => {
                  void setModelModality(value);
                  void setModelPageParam("1");
                }}
                onStatusChange={(value) => {
                  void setModelStatus(value);
                  void setModelPageParam("1");
                }}
                onPageChange={(page) => void setModelPageParam(String(page))}
                onUpdate={(model, values) =>
                  updateModel.mutate({
                    providerId,
                    modelOfferingId: model.id,
                    data: {
                      provider_model_name: values.provider_model_name,
                      alias: values.alias || null,
                      version: values.version || null,
                      modality: combinedModality(values.input_modalities, values.output_modalities),
                      input_modalities: values.input_modalities,
                      output_modalities: values.output_modalities,
                      context_window: values.context_window ?? null,
                      input_price_per_million_tokens: values.input_price_per_million_tokens ?? null,
                      output_price_per_million_tokens:
                        values.output_price_per_million_tokens ?? null,
                      cached_input_price_per_million_tokens:
                        values.cached_input_price_per_million_tokens ?? null,
                      capabilities: capabilityListToRecord(values.capabilities),
                    },
                  })
                }
                onDeactivate={(model) =>
                  deactivateModel.mutate({ providerId, modelOfferingId: model.id })
                }
                onReactivate={(model) =>
                  updateModel.mutate({
                    providerId,
                    modelOfferingId: model.id,
                    data: { is_active: true },
                  })
                }
                onTest={handleTestModel}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
      <CreateProviderCredentialSheet
        open={createCredentialOpen}
        onOpenChange={setCreateCredentialOpen}
        providerName={provider.name}
        onSubmit={(values) =>
          createCredential.mutate({
            providerId,
            data: {
              name: values.name,
              api_key: values.api_key,
            },
          })
        }
        isPending={createCredential.isPending}
      />
      <CredentialPoolSheet
        open={createPoolOpen}
        onOpenChange={setCreatePoolOpen}
        title="New credential pool"
        description={`Create a pool for ${provider.name}.`}
        submitLabel="Create pool"
        isPending={createPool.isPending}
        onSubmit={(values) =>
          createPool.mutate({
            providerId,
            data: {
              name: values.name,
              description: values.description?.trim() ? values.description : null,
              selection_policy: values.selection_policy,
            },
          })
        }
      />
      <CreateModelOfferingSheet
        open={createModelOpen}
        onOpenChange={setCreateModelOpen}
        providerName={provider.name}
        onSubmit={(values) =>
          createModel.mutate({
            providerId,
            data: {
              provider_model_name: values.provider_model_name,
              ...(values.alias ? { alias: values.alias } : {}),
              ...(values.version ? { version: values.version } : {}),
              modality: combinedModality(values.input_modalities, values.output_modalities),
              input_modalities: values.input_modalities,
              output_modalities: values.output_modalities,
              context_window: values.context_window,
              input_price_per_million_tokens: values.input_price_per_million_tokens,
              output_price_per_million_tokens: values.output_price_per_million_tokens,
              cached_input_price_per_million_tokens: values.cached_input_price_per_million_tokens,
              capabilities: capabilityListToRecord(values.capabilities),
            },
          })
        }
        isPending={createModel.isPending}
      />
    </>
  );
}

const healthLabels: Record<string, { label: string; variant: "active" | "inactive" | "error" }> = {
  valid: { label: "Valid", variant: "active" },
  unchecked: { label: "Untested", variant: "inactive" },
  invalid: { label: "Invalid", variant: "error" },
  degraded: { label: "Degraded", variant: "error" },
};

function formatHealth(status: string) {
  return healthLabels[status] ?? { label: status, variant: "inactive" as const };
}

function formatRoutingPolicy(value: string) {
  return routingPolicyOptions.find((option) => option.value === value)?.label ?? value;
}

function toRoutingPolicyValue(value: string): CredentialPoolValues["selection_policy"] {
  return routingPolicyOptions.some((option) => option.value === value)
    ? (value as CredentialPoolValues["selection_policy"])
    : "priority";
}

function CredentialPoolTable({
  pools,
  selectedPoolId,
  isLoading,
  isError,
  onSelect,
  onUpdate,
  onDeactivate,
  onReactivate,
}: {
  pools: CredentialPoolResponse[];
  selectedPoolId: string | null;
  isLoading: boolean;
  isError: boolean;
  onSelect: (poolId: string) => void;
  onUpdate: (pool: CredentialPoolResponse, values: CredentialPoolValues) => void;
  onDeactivate: (pool: CredentialPoolResponse) => void;
  onReactivate: (pool: CredentialPoolResponse) => void;
}) {
  const [editPool, setEditPool] = useState<CredentialPoolResponse | null>(null);

  return (
    <>
      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Pool</TableHead>
              <TableHead>Policy</TableHead>
              <TableHead className="text-right">Active keys</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  Loading pools...
                </TableCell>
              </TableRow>
            ) : null}
            {isError ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-destructive">
                  Pools could not be loaded.
                </TableCell>
              </TableRow>
            ) : null}
            {!isLoading && !isError && pools.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  No pools added yet.
                </TableCell>
              </TableRow>
            ) : null}
            {pools.map((pool) => {
              const isSelected = pool.id === selectedPoolId;
              return (
                <TableRow
                  key={pool.id}
                  className={cn(
                    "cursor-pointer",
                    !pool.is_active && "opacity-60",
                    isSelected && "bg-muted/40",
                  )}
                  onClick={() => onSelect(pool.id)}
                >
                  <TableCell>
                    <div className="font-medium">{pool.name}</div>
                    <p className="text-xs text-muted-foreground">
                      {pool.description || "No description"}
                    </p>
                  </TableCell>
                  <TableCell>{formatRoutingPolicy(pool.selection_policy)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {pool.active_credential_count}/{pool.credential_count}
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={pool.is_active ? "active" : "inactive"}>
                      {pool.is_active ? "Active" : "Disabled"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDateTime(pool.updated_at)}
                  </TableCell>
                  <TableCell className="flex justify-end gap-1">
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={(event) => {
                        event.stopPropagation();
                        setEditPool(pool);
                      }}
                      title="Edit pool"
                      aria-label="Edit pool"
                    >
                      <Pencil />
                    </Button>
                    {pool.is_active ? (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={(event) => {
                          event.stopPropagation();
                          onDeactivate(pool);
                        }}
                        title="Disable pool"
                        aria-label="Disable pool"
                      >
                        <Power />
                      </Button>
                    ) : (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={(event) => {
                          event.stopPropagation();
                          onReactivate(pool);
                        }}
                        title="Reactivate pool"
                        aria-label="Reactivate pool"
                      >
                        <RotateCcw />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <CredentialPoolSheet
        open={Boolean(editPool)}
        onOpenChange={(open) => !open && setEditPool(null)}
        title="Edit credential pool"
        description="Update how this pool selects active credentials."
        submitLabel="Save changes"
        initialValue={editPool}
        onSubmit={(values) => {
          if (!editPool) return;
          onUpdate(editPool, values);
          setEditPool(null);
        }}
      />
    </>
  );
}

const poolMembershipSchema = z.object({
  provider_credential_id: z.string().min(1),
  priority: z.coerce.number().int().min(0),
  weight: z.coerce.number().int().min(1),
});

type PoolMembershipInput = z.input<typeof poolMembershipSchema>;
type PoolMembershipValues = z.output<typeof poolMembershipSchema>;

function CredentialPoolMembersPanel({
  providerId,
  pool,
  credentials,
  members,
  isLoading,
  isError,
  isAdding,
  onAdd,
  onUpdate,
  onDelete,
}: {
  providerId: string;
  pool: CredentialPoolResponse | null;
  credentials: ProviderCredentialResponse[];
  members: CredentialPoolCredentialResponse[];
  isLoading: boolean;
  isError: boolean;
  isAdding: boolean;
  onAdd: (pool: CredentialPoolResponse, values: PoolMembershipValues) => void;
  onUpdate: (
    pool: CredentialPoolResponse,
    member: CredentialPoolCredentialResponse,
    values: Partial<Pick<CredentialPoolCredentialResponse, "priority" | "weight" | "is_active">>,
  ) => void;
  onDelete: (pool: CredentialPoolResponse, member: CredentialPoolCredentialResponse) => void;
}) {
  const [editMember, setEditMember] = useState<CredentialPoolCredentialResponse | null>(null);
  const form = useForm<PoolMembershipInput, unknown, PoolMembershipValues>({
    resolver: zodResolver(poolMembershipSchema),
    defaultValues: { provider_credential_id: "", priority: 100, weight: 1 },
  });
  const memberCredentialIds = new Set(members.map((member) => member.provider_credential_id));
  const availableCredentials = credentials.filter(
    (credential) => !memberCredentialIds.has(credential.id),
  );
  const firstAvailableCredentialId = availableCredentials[0]?.id ?? "";
  const selectedCredentialId = useWatch({ control: form.control, name: "provider_credential_id" });

  useEffect(() => {
    form.reset({
      provider_credential_id: firstAvailableCredentialId,
      priority: 100,
      weight: 1,
    });
  }, [pool?.id, firstAvailableCredentialId, form]);

  if (!pool) {
    return (
      <div className="rounded-md border py-8 text-center text-sm text-muted-foreground">
        Create a pool before assigning credentials.
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <div className="flex flex-col gap-3 border-b p-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h4 className="font-medium">{pool.name} credentials</h4>
          <p className="text-sm text-muted-foreground">
            Priority orders deterministic routing. Weight only affects weighted routing.
          </p>
        </div>
        <form
          className="grid gap-2 md:grid-cols-[minmax(220px,1fr)_92px_92px_auto]"
          onSubmit={form.handleSubmit((values) => {
            if (!pool) return;
            onAdd(pool, values);
          })}
        >
          <Select
            value={selectedCredentialId}
            onValueChange={(value) => form.setValue("provider_credential_id", value)}
            disabled={!providerId || availableCredentials.length === 0}
          >
            <SelectTrigger>
              <SelectValue placeholder="Credential" />
            </SelectTrigger>
            <SelectContent>
              {availableCredentials.map((credential) => (
                <SelectItem key={credential.id} value={credential.id}>
                  {credential.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            aria-label="Membership priority"
            title="Priority"
            placeholder="Priority"
            type="number"
            min={0}
            {...form.register("priority", { valueAsNumber: true })}
          />
          <Input
            aria-label="Membership weight"
            title="Weight"
            placeholder="Weight"
            type="number"
            min={1}
            {...form.register("weight", { valueAsNumber: true })}
          />
          <Button
            type="submit"
            disabled={isAdding || !providerId || availableCredentials.length === 0}
          >
            <Plus />
            Assign
          </Button>
        </form>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Credential</TableHead>
            <TableHead className="text-right">Priority</TableHead>
            <TableHead className="text-right">Weight</TableHead>
            <TableHead>Health</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-[1%]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                Loading pool credentials...
              </TableCell>
            </TableRow>
          ) : null}
          {isError ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-destructive">
                Pool credentials could not be loaded.
              </TableCell>
            </TableRow>
          ) : null}
          {!isLoading && !isError && members.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                This pool is empty. Routing through it will fail until an active credential is
                assigned.
              </TableCell>
            </TableRow>
          ) : null}
          {[...members]
            .sort((a, b) => a.priority - b.priority)
            .map((member) => {
              const health = formatHealth(member.credential.health_status);
              return (
                <TableRow
                  key={member.id}
                  className={!member.is_active || !member.credential.is_active ? "opacity-60" : ""}
                >
                  <TableCell>
                    <div className="font-medium">{member.credential.name}</div>
                    <p className="font-mono text-xs text-muted-foreground">
                      {member.credential.key_prefix}
                    </p>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">{member.priority}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{member.weight}</TableCell>
                  <TableCell>
                    <StatusBadge variant={health.variant}>{health.label}</StatusBadge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      variant={
                        member.is_active && member.credential.is_active ? "active" : "inactive"
                      }
                    >
                      {member.is_active
                        ? member.credential.is_active
                          ? "Active"
                          : "Credential disabled"
                        : "Membership disabled"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="flex justify-end">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={() => setEditMember(member)}
                        title="Edit membership"
                        aria-label="Edit membership"
                      >
                        <Pencil />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={() => onUpdate(pool, member, { is_active: !member.is_active })}
                        title={member.is_active ? "Disable membership" : "Reactivate membership"}
                        aria-label={
                          member.is_active ? "Disable membership" : "Reactivate membership"
                        }
                      >
                        {member.is_active ? <Power /> : <RotateCcw />}
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={() => onDelete(pool, member)}
                        title="Remove from pool"
                        aria-label="Remove from pool"
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>
      <PoolMembershipSheet
        member={editMember}
        onClose={() => setEditMember(null)}
        onSubmit={(values) => {
          if (!editMember) return;
          onUpdate(pool, editMember, values);
          setEditMember(null);
        }}
      />
    </div>
  );
}

function PoolMembershipSheet({
  member,
  onClose,
  onSubmit,
}: {
  member: CredentialPoolCredentialResponse | null;
  onClose: () => void;
  onSubmit: (values: Pick<PoolMembershipValues, "priority" | "weight">) => void;
}) {
  const form = useForm<
    Pick<PoolMembershipInput, "priority" | "weight">,
    unknown,
    Pick<PoolMembershipValues, "priority" | "weight">
  >({
    resolver: zodResolver(poolMembershipSchema.pick({ priority: true, weight: true })),
    defaultValues: { priority: 100, weight: 1 },
  });

  useEffect(() => {
    if (!member) return;
    form.reset({
      priority: member.priority,
      weight: member.weight,
    });
  }, [member, form]);

  return (
    <Sheet open={Boolean(member)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit pool credential</SheetTitle>
          <SheetDescription>
            Update this credential's routing metadata for this pool only.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="pool-membership-priority">Priority</Label>
            <Input
              id="pool-membership-priority"
              type="number"
              min={0}
              {...form.register("priority", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Lower numbers are preferred by priority and fallback policies.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pool-membership-weight">Weight</Label>
            <Input
              id="pool-membership-weight"
              type="number"
              min={1}
              {...form.register("weight", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Higher numbers receive more traffic only when this pool uses weighted routing.
            </p>
          </div>
        </form>
        <SheetFooter>
          <Button disabled={!member} onClick={form.handleSubmit(onSubmit)}>
            Save changes
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CredentialPoolSheet({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  initialValue,
  isPending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  submitLabel: string;
  initialValue?: CredentialPoolResponse | null;
  isPending?: boolean;
  onSubmit: (values: CredentialPoolValues) => void;
}) {
  const form = useForm<CredentialPoolValues>({
    resolver: zodResolver(credentialPoolSchema),
    defaultValues: {
      name: "",
      description: "",
      selection_policy: "priority",
    },
  });
  const selectedPolicy = useWatch({ control: form.control, name: "selection_policy" });

  useEffect(() => {
    if (!open) return;
    form.reset({
      name: initialValue?.name ?? "",
      description: initialValue?.description ?? "",
      selection_policy: toRoutingPolicyValue(initialValue?.selection_policy ?? "priority"),
    });
  }, [open, initialValue, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="credential-pool-name">Name</Label>
            <Input id="credential-pool-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="credential-pool-description">Description</Label>
            <Textarea id="credential-pool-description" {...form.register("description")} />
          </div>
          <div className="space-y-1.5">
            <Label>Selection policy</Label>
            <Select
              value={selectedPolicy}
              onValueChange={(value) =>
                form.setValue("selection_policy", value as CredentialPoolValues["selection_policy"])
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {routingPolicyOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {routingPolicyOptions.find((option) => option.value === selectedPolicy)?.description}
            </p>
          </div>
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Saving..." : submitLabel}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function ResourceKeyTable({
  providerId,
  credentials,
  isLoading,
  isError,
  isTesting,
  onUpdate,
  onRotate,
  onDeactivate,
  onReactivate,
  onTest,
}: {
  providerId: string;
  credentials: ProviderCredentialResponse[];
  isLoading: boolean;
  isError: boolean;
  isTesting: boolean;
  onUpdate: (credential: ProviderCredentialResponse, values: { name: string }) => void;
  onRotate: (credential: ProviderCredentialResponse, apiKey: string) => void;
  onDeactivate: (credential: ProviderCredentialResponse) => void;
  onReactivate: (credential: ProviderCredentialResponse) => void;
  onTest: (credential: ProviderCredentialResponse) => void;
}) {
  const sortedCredentials = [...credentials].sort(
    (a, b) =>
      Number(b.is_active) - Number(a.is_active) ||
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  const syncCredential = sortedCredentials.find((credential) => credential.is_active);
  const [editCredential, setEditCredential] = useState<ProviderCredentialResponse | null>(null);
  const [rotateCredential, setRotateCredential] = useState<ProviderCredentialResponse | null>(null);
  const [apiKey, setApiKey] = useState("");

  return (
    <>
      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Credential</TableHead>
              <TableHead>Prefix</TableHead>
              <TableHead>Health</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Last success</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
                  Loading credentials...
                </TableCell>
              </TableRow>
            ) : null}
            {isError ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-sm text-destructive">
                  Credentials could not be loaded.
                </TableCell>
              </TableRow>
            ) : null}
            {!isLoading && !isError && sortedCredentials.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
                  No credentials added yet.
                </TableCell>
              </TableRow>
            ) : null}
            {sortedCredentials.map((credential) => {
              const health = formatHealth(credential.health_status);
              return (
                <TableRow key={credential.id}>
                  <TableCell className="font-medium">
                    <div>{credential.name}</div>
                    <p className="text-xs text-muted-foreground">
                      Created by {credential.created_by ?? "system"}
                    </p>
                    {syncCredential?.id === credential.id ? (
                      <p className="text-xs text-muted-foreground">Used first for model sync</p>
                    ) : null}
                    {credential.last_validation_error ? (
                      <p className="text-xs text-destructive">
                        {sanitizeCredentialValidationMessage(credential.last_validation_error)}
                      </p>
                    ) : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{credential.key_prefix}</TableCell>
                  <TableCell>
                    <StatusBadge variant={health.variant}>{health.label}</StatusBadge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={credential.is_active ? "active" : "inactive"}>
                      {credential.is_active ? "Active" : "Disabled"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDateTime(credential.created_at)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {credential.last_successful_request_at
                      ? formatDateTime(credential.last_successful_request_at)
                      : "Never"}
                  </TableCell>
                  <TableCell className="flex justify-end gap-1">
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      disabled={!providerId || !credential.is_active || isTesting}
                      onClick={() => onTest(credential)}
                      title="Test credential"
                      aria-label="Test credential"
                    >
                      <Activity />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => setEditCredential(credential)}
                      title="Edit credential"
                      aria-label="Edit credential"
                    >
                      <Pencil />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => setRotateCredential(credential)}
                      title="Rotate credential secret"
                      aria-label="Rotate credential secret"
                    >
                      <RefreshCw />
                    </Button>
                    {credential.is_active ? (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        disabled={!providerId}
                        onClick={() => onDeactivate(credential)}
                        title="Disable credential"
                        aria-label="Disable credential"
                      >
                        <Power />
                      </Button>
                    ) : (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        disabled={!providerId}
                        onClick={() => onReactivate(credential)}
                        title="Reactivate credential"
                        aria-label="Reactivate credential"
                      >
                        <RotateCcw />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <EditProviderCredentialSheet
        providerCredential={editCredential}
        onClose={() => setEditCredential(null)}
        onSubmit={(values) => {
          if (!editCredential) return;
          onUpdate(editCredential, values);
          setEditCredential(null);
        }}
      />
      <Dialog
        open={Boolean(rotateCredential)}
        onOpenChange={(open) => {
          if (!open) {
            setRotateCredential(null);
            setApiKey("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rotate {rotateCredential?.name ?? "credential"}</DialogTitle>
            <DialogDescription>
              The current key stops working as soon as you save. Make sure the new key is active
              before rotating.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Current prefix</span>
              <span className="font-mono">{rotateCredential?.key_prefix ?? "—"}</span>
            </div>
            <Label htmlFor="rotate-api-key" className="text-xs">
              New API key
            </Label>
            <Input
              id="rotate-api-key"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={!rotateCredential || !apiKey}
              onClick={() => {
                if (rotateCredential) onRotate(rotateCredential, apiKey);
                setRotateCredential(null);
                setApiKey("");
              }}
            >
              Rotate
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

function EditProviderCredentialSheet({
  providerCredential,
  onClose,
  onSubmit,
}: {
  providerCredential: ProviderCredentialResponse | null;
  onClose: () => void;
  onSubmit: (values: { name: string }) => void;
}) {
  const form = useForm<{ name: string }>({
    resolver: zodResolver(
      z.object({
        name: z.string().min(1).max(255),
      }),
    ),
    defaultValues: { name: "" },
  });

  useEffect(() => {
    if (providerCredential) {
      form.reset({
        name: providerCredential.name,
      });
    }
  }, [providerCredential, form]);

  return (
    <Sheet open={Boolean(providerCredential)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit credential</SheetTitle>
          <SheetDescription>
            Rename this provider credential. Pool membership, priority, and weight are managed from
            the Pools tab.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-key-name">Name</Label>
            <Input id="edit-provider-key-name" autoFocus {...form.register("name")} />
          </div>
        </form>
        <SheetFooter>
          <Button onClick={form.handleSubmit(onSubmit)}>Save changes</Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CreateProviderCredentialSheet({
  open,
  onOpenChange,
  providerName,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providerName: string;
  onSubmit: (values: ProviderCredentialValues) => void;
  isPending: boolean;
}) {
  const form = useForm<ProviderCredentialValues>({
    resolver: zodResolver(providerCredentialSchema),
    defaultValues: { name: "", api_key: "" },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        name: `${providerName} credential`,
        api_key: "",
      });
    }
  }, [open, providerName, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add credential</SheetTitle>
          <SheetDescription>
            Add an encrypted upstream API key for {providerName}. Assign it to pools after saving.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-key-name">Name</Label>
            <Input id="detail-provider-key-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-key-secret">API key</Label>
            <Input
              id="detail-provider-key-secret"
              type="password"
              autoComplete="new-password"
              {...form.register("api_key")}
            />
          </div>
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Adding..." : "Add credential"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CreateModelOfferingSheet({
  open,
  onOpenChange,
  providerName,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providerName: string;
  onSubmit: (values: ModelOfferingValues) => void;
  isPending: boolean;
}) {
  const form = useForm<ModelOfferingFormInput, unknown, ModelOfferingValues>({
    resolver: zodResolver(modelOfferingSchema),
    defaultValues: {
      provider_model_name: "",
      alias: "",
      version: "",
      input_modalities: ["text"],
      output_modalities: ["text"],
      context_window: undefined,
      input_price_per_million_tokens: undefined,
      output_price_per_million_tokens: undefined,
      cached_input_price_per_million_tokens: undefined,
      capabilities: ["chat", "streaming"],
    },
  });
  const inputModalities = useWatch({ control: form.control, name: "input_modalities" });
  const outputModalities = useWatch({ control: form.control, name: "output_modalities" });
  const capabilities = useWatch({ control: form.control, name: "capabilities" });

  useEffect(() => {
    if (open) {
      form.reset({
        provider_model_name: "",
        alias: "",
        version: "",
        input_modalities: ["text"],
        output_modalities: ["text"],
        context_window: undefined,
        input_price_per_million_tokens: undefined,
        output_price_per_million_tokens: undefined,
        cached_input_price_per_million_tokens: undefined,
        capabilities: ["chat", "streaming"],
      });
    }
  }, [open, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add model</SheetTitle>
          <SheetDescription>
            Register a model exposed by {providerName}. Alias is optional and provider-scoped.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-name">Provider model name</Label>
            <Input
              id="detail-provider-model-name"
              autoFocus
              placeholder="gpt-5.4-mini"
              {...form.register("provider_model_name")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-alias">Alias</Label>
            <Input
              id="detail-provider-model-alias"
              placeholder="fast"
              {...form.register("alias")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-version">Version</Label>
            <Input
              id="detail-provider-model-version"
              placeholder="2025-08-07"
              {...form.register("version")}
            />
          </div>
          <ModalityCheckboxGroup
            label="Input modalities"
            values={inputModalities ?? []}
            onChange={(values) => form.setValue("input_modalities", values)}
          />
          <ModalityCheckboxGroup
            label="Output modalities"
            values={outputModalities ?? []}
            onChange={(values) => form.setValue("output_modalities", values)}
          />
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-context">Context window</Label>
            <Input
              id="detail-provider-model-context"
              type="number"
              min={1}
              placeholder="128000"
              {...form.register("context_window")}
            />
          </div>
          <PricingFields register={form.register} prefix="detail" />
          <CapabilityCheckboxGroup
            values={capabilities ?? []}
            onChange={(values) => form.setValue("capabilities", values)}
          />
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Adding..." : "Add model"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function PricingFields({
  register,
  prefix,
}: {
  register: UseFormRegister<ModelOfferingFormInput>;
  prefix: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label>Pricing (USD per 1M tokens)</Label>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1.5">
          <Label
            htmlFor={`${prefix}-provider-model-input-price`}
            className="text-xs text-muted-foreground"
          >
            Input
          </Label>
          <Input
            id={`${prefix}-provider-model-input-price`}
            type="number"
            min={0}
            placeholder="0"
            {...register("input_price_per_million_tokens")}
          />
        </div>
        <div className="space-y-1.5">
          <Label
            htmlFor={`${prefix}-provider-model-output-price`}
            className="text-xs text-muted-foreground"
          >
            Output
          </Label>
          <Input
            id={`${prefix}-provider-model-output-price`}
            type="number"
            min={0}
            placeholder="0"
            {...register("output_price_per_million_tokens")}
          />
        </div>
        <div className="space-y-1.5">
          <Label
            htmlFor={`${prefix}-provider-model-cached-price`}
            className="text-xs text-muted-foreground"
          >
            Cached input
          </Label>
          <Input
            id={`${prefix}-provider-model-cached-price`}
            type="number"
            min={0}
            placeholder="0"
            {...register("cached_input_price_per_million_tokens")}
          />
        </div>
      </div>
    </div>
  );
}

function ResourceModelTable({
  providerId,
  models,
  total,
  limit,
  offset,
  search,
  modality,
  status,
  page,
  isLoading,
  isError,
  hasActiveCredential,
  isTesting,
  onSearchChange,
  onModalityChange,
  onStatusChange,
  onPageChange,
  onUpdate,
  onDeactivate,
  onReactivate,
  onTest,
}: {
  providerId: string;
  models: ModelOfferingResponse[];
  total: number;
  limit: number;
  offset: number;
  search: string;
  modality: string;
  status: string;
  page: number;
  isLoading: boolean;
  isError: boolean;
  hasActiveCredential: boolean;
  isTesting: boolean;
  onSearchChange: (value: string) => void;
  onModalityChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onPageChange: (page: number) => void;
  onUpdate: (model: ModelOfferingResponse, values: ModelOfferingValues) => void;
  onDeactivate: (model: ModelOfferingResponse) => void;
  onReactivate: (model: ModelOfferingResponse) => void;
  onTest: (model: ModelOfferingResponse) => void;
}) {
  const [editModel, setEditModel] = useState<ModelOfferingResponse | null>(null);
  const editForm = useForm<ModelOfferingFormInput, unknown, ModelOfferingValues>({
    resolver: zodResolver(modelOfferingSchema),
    defaultValues: {
      provider_model_name: "",
      alias: "",
      version: "",
      input_modalities: ["text"],
      output_modalities: ["text"],
      context_window: undefined,
      input_price_per_million_tokens: undefined,
      output_price_per_million_tokens: undefined,
      cached_input_price_per_million_tokens: undefined,
      capabilities: [],
    },
  });
  const editInputModalities = useWatch({ control: editForm.control, name: "input_modalities" });
  const editOutputModalities = useWatch({ control: editForm.control, name: "output_modalities" });
  const editCapabilities = useWatch({ control: editForm.control, name: "capabilities" });
  const selectedModalities = modality === "all" ? [] : modality.split(",").filter(Boolean);
  const pageCount = Math.max(Math.ceil(total / limit), 1);
  const safePage = Math.min(page, pageCount);
  const hasFilters = Boolean(search.trim()) || modality !== "all" || status !== "all";

  useEffect(() => {
    if (!editModel) return;
    editForm.reset({
      provider_model_name: editModel.provider_model_name,
      alias: editModel.alias ?? "",
      version: editModel.version ?? "",
      input_modalities: editModel.input_modalities?.length
        ? editModel.input_modalities
        : editModel.modality.split("+"),
      output_modalities: editModel.output_modalities?.length
        ? editModel.output_modalities
        : ["text"],
      context_window: editModel.context_window ?? undefined,
      input_price_per_million_tokens: editModel.input_price_per_million_tokens ?? undefined,
      output_price_per_million_tokens: editModel.output_price_per_million_tokens ?? undefined,
      cached_input_price_per_million_tokens:
        editModel.cached_input_price_per_million_tokens ?? undefined,
      capabilities: capabilityRecordToList(editModel.capabilities),
    });
  }, [editModel, editForm]);

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto]">
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search models or aliases..."
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                {selectedModalities.length
                  ? `Modalities: ${selectedModalities.join(", ")}`
                  : "All modalities"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Required modalities</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuCheckboxItem
                checked={selectedModalities.length === 0}
                onCheckedChange={() => onModalityChange("all")}
              >
                All modalities
              </DropdownMenuCheckboxItem>
              {modelModalities.map((item) => {
                const next = selectedModalities.includes(item)
                  ? selectedModalities.filter((value) => value !== item)
                  : [...selectedModalities, item];
                return (
                  <DropdownMenuCheckboxItem
                    key={item}
                    checked={selectedModalities.includes(item)}
                    onCheckedChange={() => onModalityChange(next.length ? next.join(",") : "all")}
                  >
                    {item}
                  </DropdownMenuCheckboxItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
          <Select value={status} onValueChange={onStatusChange}>
            <SelectTrigger>
              <SelectValue placeholder="Filter by status" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="disabled">Disabled</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        {isLoading ? (
          <p className="rounded-lg border py-8 text-center text-sm text-muted-foreground">
            Loading model offerings...
          </p>
        ) : null}
        {isError ? (
          <p className="rounded-lg border py-8 text-center text-sm text-destructive">
            Models could not be loaded.
          </p>
        ) : null}
        {!isLoading && !isError && total === 0 && !hasFilters ? (
          <p className="rounded-lg border py-8 text-center text-sm text-muted-foreground">
            No models added yet.
          </p>
        ) : null}
        {!isLoading && !isError && total === 0 && hasFilters ? (
          <p className="rounded-lg border py-8 text-center text-sm text-muted-foreground">
            No models match these filters.
          </p>
        ) : null}

        {models.length > 0 ? (
          <div className="overflow-hidden rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Modalities</TableHead>
                  <TableHead className="text-right">Context</TableHead>
                  <TableHead className="text-right">Price (in/out)</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[1%]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.map((model) => {
                  const activeCapabilities = capabilityRecordToList(model.capabilities);
                  return (
                    <TableRow
                      key={model.id}
                      className={!model.is_active ? "opacity-60" : undefined}
                    >
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span className="font-mono text-sm font-medium">
                            {model.provider_model_name}
                          </span>
                          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                            {model.alias ? <span>alias: {model.alias}</span> : null}
                            {model.version ? <span>v{model.version}</span> : null}
                            {activeCapabilities.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {activeCapabilities.map((capability) => (
                                  <span
                                    key={capability}
                                    className="rounded border bg-muted/40 px-1.5 py-0.5 text-[10px]"
                                  >
                                    {capability}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <span>{formatModalities(model.input_modalities)}</span>
                          <span aria-hidden>→</span>
                          <span>{formatModalities(model.output_modalities)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {model.context_window ? model.context_window.toLocaleString() : "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatTokenPrice(model.input_price_per_million_tokens)} /{" "}
                        {formatTokenPrice(model.output_price_per_million_tokens)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        <div className="flex flex-col">
                          <span>{model.metadata_source}</span>
                          {model.metadata_last_synced_at ? (
                            <span className="text-[11px]">
                              {formatRelativeFromNow(model.metadata_last_synced_at)}
                            </span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge variant={model.is_active ? "active" : "inactive"}>
                          {model.is_active ? "Active" : "Disabled"}
                        </StatusBadge>
                      </TableCell>
                      <TableCell className="flex justify-end gap-1">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          disabled={
                            !providerId || !model.is_active || !hasActiveCredential || isTesting
                          }
                          onClick={() => onTest(model)}
                          title={
                            !hasActiveCredential
                              ? "Add an active credential before testing models."
                              : "Test model"
                          }
                          aria-label="Test model"
                        >
                          <Activity />
                        </Button>
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          onClick={() => setEditModel(model)}
                          title="Edit model"
                          aria-label="Edit model"
                        >
                          <Pencil />
                        </Button>
                        {model.is_active ? (
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            disabled={!providerId}
                            onClick={() => onDeactivate(model)}
                            title="Disable model"
                            aria-label="Disable model"
                          >
                            <Power />
                          </Button>
                        ) : (
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            disabled={!providerId}
                            onClick={() => onReactivate(model)}
                            title="Reactivate model"
                            aria-label="Reactivate model"
                          >
                            <RotateCcw />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : null}

        {total > limit ? (
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              Page {safePage} of {pageCount} · showing {offset + 1}-
              {Math.min(offset + models.length, total)} of {total}
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={safePage <= 1}
                onClick={() => onPageChange(safePage - 1)}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={safePage >= pageCount}
                onClick={() => onPageChange(safePage + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
      <Sheet open={Boolean(editModel)} onOpenChange={(open) => !open && setEditModel(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit model</SheetTitle>
            <SheetDescription>
              Update the model metadata Bab uses for display, filtering, and routing decisions.
            </SheetDescription>
          </SheetHeader>
          <form
            className="grid gap-4 px-4"
            onSubmit={editForm.handleSubmit((values) => {
              if (editModel) onUpdate(editModel, values);
              setEditModel(null);
            })}
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-name">Provider model name</Label>
              <Input id="edit-provider-model-name" {...editForm.register("provider_model_name")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-alias">Alias</Label>
              <Input id="edit-provider-model-alias" {...editForm.register("alias")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-version">Version</Label>
              <Input id="edit-provider-model-version" {...editForm.register("version")} />
            </div>
            <ModalityCheckboxGroup
              label="Input modalities"
              values={editInputModalities ?? []}
              onChange={(values) => editForm.setValue("input_modalities", values)}
            />
            <ModalityCheckboxGroup
              label="Output modalities"
              values={editOutputModalities ?? []}
              onChange={(values) => editForm.setValue("output_modalities", values)}
            />
            <div className="space-y-1.5">
              <Label htmlFor="edit-provider-model-context">Context window</Label>
              <Input
                id="edit-provider-model-context"
                type="number"
                min={1}
                {...editForm.register("context_window")}
              />
            </div>
            <PricingFields register={editForm.register} prefix="edit" />
            <CapabilityCheckboxGroup
              values={editCapabilities ?? []}
              onChange={(values) => editForm.setValue("capabilities", values)}
            />
          </form>
          <SheetFooter>
            <Button
              disabled={!editModel}
              onClick={editForm.handleSubmit((values) => {
                if (editModel) onUpdate(editModel, values);
                setEditModel(null);
              })}
            >
              Save
            </Button>
            <SheetClose asChild>
              <Button variant="outline">Cancel</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}

function ModalityCheckboxGroup({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {modelModalities.map((item) => (
          <CheckboxOption
            key={item}
            label={item}
            checked={values.includes(item)}
            onCheckedChange={(checked) => {
              const next = checked ? [...values, item] : values.filter((value) => value !== item);
              onChange(next.length ? next : ["text"]);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function CapabilityCheckboxGroup({
  values,
  onChange,
}: {
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>Capabilities</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {modelCapabilityOptions.map((item) => (
          <CheckboxOption
            key={item}
            label={item}
            checked={values.includes(item)}
            onCheckedChange={(checked) => {
              const next = checked ? [...values, item] : values.filter((value) => value !== item);
              onChange(next);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function CheckboxOption({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border p-2 text-sm">
      <Checkbox checked={checked} onCheckedChange={(value) => onCheckedChange(value === true)} />
      <span>{label}</span>
    </label>
  );
}
