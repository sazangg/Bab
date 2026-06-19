import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { Activity, ChevronDown, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useDeleteCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdDelete,
  useAddCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPost,
  useCreateCredentialPoolApiV1ProvidersProviderIdPoolsPost,
  useCreateProviderModelOffering,
  useCreateProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useDeactivateProviderModelOffering,
  useDeactivateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdDelete,
  useListCredentialPoolCredentialsApiV1ProvidersProviderIdPoolsPoolIdCredentialsGet,
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListProviderModelOfferings,
  useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet,
  useGetCredentialPoolImpactApiV1ProvidersProviderIdPoolsPoolIdImpactGet,
  useGetProviderModelOfferingImpact,
  useGetProviderCredentialImpactApiV1ProvidersProviderIdCredentialsProviderCredentialIdImpactGet,
  useSyncProviderModelOfferings,
  useTestProviderModelOffering,
  useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost,
  useUpdateCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdPatch,
  useUpdateCredentialPoolApiV1ProvidersProviderIdPoolsPoolIdPatch,
  useUpdateProviderModelOffering,
  useUpdateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdPatch,
} from "@/shared/api/generated/providers/providers";
import type {
  CredentialPoolResponse,
  ProviderModelOfferingResponse,
  ProviderCredentialResponse,
  ProviderResponse,
  SyncProviderModelOfferingsResponse,
} from "@/shared/api/generated/schemas";

import {
  capabilityListToRecord,
  combinedModality,
  dollarsToCents,
  sanitizeCredentialValidationMessage,
} from "../lib/format";
import { CreateModelOfferingSheet } from "./resources/CreateModelOfferingSheet";
import { CreateProviderCredentialSheet } from "./resources/CreateProviderCredentialSheet";
import { CredentialPoolMembersPanel } from "./resources/CredentialPoolMembersPanel";
import { CredentialPoolSheet } from "./resources/CredentialPoolSheet";
import { CredentialPoolsTable } from "./resources/CredentialPoolsTable";
import { CredentialsTable } from "./resources/CredentialsTable";
import { ModelSyncSummary } from "./resources/ModelSyncSummary";
import { ModelsTable } from "./resources/ModelsTable";
import { ProviderSetupChecklist } from "./resources/ProviderSetupChecklist";
import { ResourceImpactDialog } from "./resources/ResourceImpactDialog";

export function ProviderResourcesPanel({
  provider,
  canManage,
}: {
  provider: ProviderResponse;
  canManage: boolean;
}) {
  return <ProviderResourcesContent provider={provider} canManage={canManage} />;
}

function ProviderResourcesContent({
  provider,
  canManage,
}: {
  provider: ProviderResponse;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const providerId = provider.id;
  const [tab, setTab] = useQueryState("tab", { defaultValue: "credentials" });
  const [resourceAction, setResourceAction] = useQueryState("action", { defaultValue: "" });
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
  const [lastSync, setLastSync] = useState<SyncProviderModelOfferingsResponse | null>(null);
  const [selectedPoolId, setSelectedPoolId] = useState<string | null>(null);
  const [deactivateCredentialTarget, setDeactivateCredentialTarget] =
    useState<ProviderCredentialResponse | null>(null);
  const [deactivatePoolTarget, setDeactivatePoolTarget] = useState<CredentialPoolResponse | null>(
    null,
  );
  const [deactivateModelTarget, setDeactivateModelTarget] =
    useState<ProviderModelOfferingResponse | null>(null);
  const [bulkTestProgress, setBulkTestProgress] = useState<{ index: number; total: number } | null>(
    null,
  );
  const credentialSheetOpen =
    createCredentialOpen || (canManage && resourceAction === "add-credential");

  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    providerId,
    { query: { enabled: Boolean(providerId) } },
  );
  const modelsQuery = useListProviderModelOfferings(
    providerId,
    modelParams,
    { query: { enabled: Boolean(providerId), placeholderData: keepPreviousData } },
  );
  const credentialImpactQuery =
    useGetProviderCredentialImpactApiV1ProvidersProviderIdCredentialsProviderCredentialIdImpactGet(
      providerId,
      deactivateCredentialTarget?.id ?? "",
      { query: { enabled: Boolean(deactivateCredentialTarget) } },
    );
  const poolImpactQuery = useGetCredentialPoolImpactApiV1ProvidersProviderIdPoolsPoolIdImpactGet(
    providerId,
    deactivatePoolTarget?.id ?? "",
    { query: { enabled: Boolean(deactivatePoolTarget) } },
  );
  const modelImpactQuery =
    useGetProviderModelOfferingImpact(
      providerId,
      deactivateModelTarget?.id ?? "",
      { query: { enabled: Boolean(deactivateModelTarget) } },
    );
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const hasActivePool = pools.some((pool) => pool.is_active);
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
  const shouldOpenConfigurePoolSheet =
    canManage &&
    resourceAction === "configure-pool" &&
    !poolsQuery.isPending &&
    !hasActivePool;
  const poolSheetOpen = createPoolOpen || shouldOpenConfigurePoolSheet;

  useEffect(() => {
    if (resourceAction !== "configure-pool" || poolsQuery.isPending) return;
    if (hasActivePool) {
      void setResourceAction(null);
    }
  }, [hasActivePool, poolsQuery.isPending, resourceAction, setResourceAction]);

  const createPool = useCreateCredentialPoolApiV1ProvidersProviderIdPoolsPost({
    mutation: {
      onSuccess: async () => {
        setCreatePoolOpen(false);
        if (resourceAction === "configure-pool") void setResourceAction(null);
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
      { mutation: { onSuccess: async () => queryClient.invalidateQueries() } },
    );
  const deletePoolCredential =
    useDeleteCredentialPoolCredentialApiV1ProvidersProviderIdPoolsPoolIdCredentialsPoolCredentialIdDelete(
      { mutation: { onSuccess: async () => queryClient.invalidateQueries() } },
    );
  const createCredential = useCreateProviderCredentialApiV1ProvidersProviderIdCredentialsPost({
    mutation: {
      onSuccess: async () => {
        setCreateCredentialOpen(false);
        if (resourceAction === "add-credential") void setResourceAction(null);
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
  const createModel = useCreateProviderModelOffering({
    mutation: {
      onSuccess: async () => {
        setCreateModelOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateModel = useUpdateProviderModelOffering({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const deactivateModel =
    useDeactivateProviderModelOffering({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const syncModels = useSyncProviderModelOfferings({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          setLastSync(response.data);
          const summary = response.data.summary;
          toast.success(
            `Sync complete: ${summary?.added ?? 0} added, ${summary?.updated ?? 0} updated, ${summary?.reactivated ?? 0} reactivated, ${summary?.disabled ?? 0} disabled, ${summary?.unchanged ?? 0} unchanged.`,
          );
        }
        await queryClient.invalidateQueries();
      },
    },
  });
  const testCredential =
    useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost({
      mutation: { onSettled: async () => queryClient.invalidateQueries() },
    });
  const testModel = useTestProviderModelOffering({
    mutation: { onSettled: async () => queryClient.invalidateQueries() },
  });
  const hasActiveCredential = credentials.some((credential) => credential.is_active);
  const supportsModelSync =
    provider.integration_capabilities?.openai_compatible_models_list === true ||
    provider.integration_capabilities?.native_anthropic_models_list === true;
  const supportsModelTest =
    provider.integration_capabilities?.openai_compatible_chat === true ||
    provider.integration_capabilities?.native_anthropic_messages === true;
  const providerReady = provider.readiness?.status === "ready";

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

  function handleTestModel(model: ProviderModelOfferingResponse) {
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

  async function handleRotateCredential(credential: ProviderCredentialResponse, apiKey: string) {
    try {
      const updateResponse = await updateCredential.mutateAsync({
        providerId,
        providerCredentialId: credential.id,
        data: { api_key: apiKey },
      });
      if (updateResponse.status !== 200) {
        toast.error("Credential secret was not replaced.");
        return false;
      }
      const testResponse = await testCredential.mutateAsync({
        providerId,
        providerCredentialId: credential.id,
      });
      if (testResponse.status === 200 && testResponse.data.health_status === "valid") {
        toast.success(`${credential.name}: secret replaced and validated.`);
        return true;
      }
      const message =
        sanitizeCredentialValidationMessage(
          testResponse.status === 200 ? testResponse.data.last_validation_error : null,
        ) ?? "Secret was replaced, but validation failed.";
      toast.error(`${credential.name}: ${message}`);
      return false;
    } catch {
      toast.error(`${credential.name}: secret replacement failed.`);
      return false;
    }
  }

  return (
    <>
      <ProviderSetupChecklist
        providerReady={providerReady}
        canManage={canManage}
        credentials={credentials}
        pools={pools}
        hasActiveCredential={hasActiveCredential}
        activeModelCount={provider.readiness?.active_model_count ?? 0}
        onAddCredential={() => {
          void setTab("credentials");
          setCreateCredentialOpen(true);
        }}
        onTestAllCredentials={handleTestAllCredentials}
        onCreatePool={() => {
          void setTab("pools");
          setCreatePoolOpen(true);
        }}
        onOpenPools={() => void setTab("pools")}
        onOpenModels={() => void setTab("models")}
      />

      <Card>
        <CardHeader>
          <CardTitle>Provider resources</CardTitle>
          <CardDescription>
            Pools group credentials for access policies. Models define what this provider can serve.
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
                {canManage ? (
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
                ) : null}
              </div>
              <CredentialsTable
                providerId={providerId}
                credentials={credentials}
                isLoading={credentialsQuery.isPending}
                isError={credentialsQuery.isError}
                isTesting={testCredential.isPending}
                onUpdate={(credential, values) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: { name: values.name },
                  })
                }
                onRotate={handleRotateCredential}
                onDeactivate={setDeactivateCredentialTarget}
                onReactivate={(credential) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: { is_active: true },
                  })
                }
                onTest={handleTestCredential}
                canManage={canManage}
              />
            </TabsContent>

            <TabsContent value="pools" className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Credential pools</h3>
                  <p className="text-sm text-muted-foreground">
                    Pools are the routing resources access policy routes point to.
                  </p>
                </div>
                {canManage ? (
                  <Button size="sm" onClick={() => setCreatePoolOpen(true)}>
                    <Plus />
                    New pool
                  </Button>
                ) : null}
              </div>
              <CredentialPoolsTable
                pools={pools}
                selectedPoolId={selectedPool?.id ?? null}
                isLoading={poolsQuery.isPending}
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
                onDeactivate={setDeactivatePoolTarget}
                onReactivate={(pool) =>
                  updatePool.mutate({ providerId, poolId: pool.id, data: { is_active: true } })
                }
                canManage={canManage}
              />
              <CredentialPoolMembersPanel
                providerId={providerId}
                pool={selectedPool}
                credentials={credentials}
                members={poolCredentials}
                isLoading={poolCredentialsQuery.isPending}
                isError={poolCredentialsQuery.isError}
                isAdding={addPoolCredential.isPending}
                onAdd={(pool, values) =>
                  addPoolCredential.mutate({ providerId, poolId: pool.id, data: values })
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
                canManage={canManage}
              />
            </TabsContent>

            <TabsContent value="models" className="flex flex-col gap-4">
              {lastSync ? <ModelSyncSummary result={lastSync} /> : null}
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Models</h3>
                  <p className="text-sm text-muted-foreground">
                    {modelsPage.total.toLocaleString()} models · sync mode{" "}
                    {provider.model_sync_mode ?? "inherited"}
                    {lastSync ? " · synced just now" : ""}
                  </p>
                </div>
                {canManage ? (
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
                          disabled={
                            !providerId ||
                            !hasActiveCredential ||
                            !supportsModelSync ||
                            syncModels.isPending
                          }
                          title={
                            !hasActiveCredential
                              ? "Add an active credential before syncing models."
                              : !supportsModelSync
                                ? "This provider does not expose a supported models-list capability."
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
                ) : null}
              </div>
              <ModelsTable
                providerId={providerId}
                models={modelsPage.items}
                total={modelsPage.total}
                limit={modelsPage.limit}
                offset={modelsPage.offset}
                search={modelSearch}
                modality={modelModality}
                status={modelStatus}
                page={modelPage}
                isLoading={modelsQuery.isPending}
                isError={modelsQuery.isError}
                hasActiveCredential={hasActiveCredential}
                supportsModelTest={supportsModelTest}
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
                onPageChange={(nextPage) => void setModelPageParam(String(nextPage))}
                onUpdate={(model, values) =>
                  updateModel.mutate({
                    providerId,
                    modelOfferingId: model.id,
                    data: {
                      provider_model_name: values.provider_model_name,
                      version: values.version || null,
                      modality: combinedModality(values.input_modalities, values.output_modalities),
                      input_modalities: values.input_modalities,
                      output_modalities: values.output_modalities,
                      context_window: values.context_window ?? null,
                      input_price_per_million_tokens: dollarsToCents(
                        values.input_price_per_million_tokens,
                      ),
                      output_price_per_million_tokens: dollarsToCents(
                        values.output_price_per_million_tokens,
                      ),
                      cached_input_price_per_million_tokens: dollarsToCents(
                        values.cached_input_price_per_million_tokens,
                      ),
                      capabilities: capabilityListToRecord(values.capabilities),
                    },
                  })
                }
                onDeactivate={setDeactivateModelTarget}
                onReactivate={(model) =>
                  updateModel.mutate({
                    providerId,
                    modelOfferingId: model.id,
                    data: { is_active: true },
                  })
                }
                onTest={handleTestModel}
                canManage={canManage}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <ResourceImpactDialog
        open={Boolean(deactivateCredentialTarget)}
        title={`Disable ${deactivateCredentialTarget?.name ?? "credential"}?`}
        impact={credentialImpactQuery.data?.status === 200 ? credentialImpactQuery.data.data : null}
        loading={credentialImpactQuery.isPending}
        onOpenChange={(open) => !open && setDeactivateCredentialTarget(null)}
        onConfirm={() => {
          if (!deactivateCredentialTarget) return;
          deactivateCredential.mutate(
            { providerId, providerCredentialId: deactivateCredentialTarget.id },
            { onSuccess: () => setDeactivateCredentialTarget(null) },
          );
        }}
      />
      <ResourceImpactDialog
        open={Boolean(deactivatePoolTarget)}
        title={`Disable ${deactivatePoolTarget?.name ?? "pool"}?`}
        impact={poolImpactQuery.data?.status === 200 ? poolImpactQuery.data.data : null}
        loading={poolImpactQuery.isPending}
        onOpenChange={(open) => !open && setDeactivatePoolTarget(null)}
        onConfirm={() => {
          if (!deactivatePoolTarget) return;
          updatePool.mutate(
            { providerId, poolId: deactivatePoolTarget.id, data: { is_active: false } },
            { onSuccess: () => setDeactivatePoolTarget(null) },
          );
        }}
      />
      <ResourceImpactDialog
        open={Boolean(deactivateModelTarget)}
        title={`Disable ${deactivateModelTarget?.provider_model_name ?? "model"}?`}
        impact={modelImpactQuery.data?.status === 200 ? modelImpactQuery.data.data : null}
        loading={modelImpactQuery.isPending}
        onOpenChange={(open) => !open && setDeactivateModelTarget(null)}
        onConfirm={() => {
          if (!deactivateModelTarget) return;
          deactivateModel.mutate(
            { providerId, modelOfferingId: deactivateModelTarget.id },
            { onSuccess: () => setDeactivateModelTarget(null) },
          );
        }}
      />
      {canManage ? (
        <CreateProviderCredentialSheet
          open={credentialSheetOpen}
          onOpenChange={(open) => {
            setCreateCredentialOpen(open);
            if (!open && resourceAction) void setResourceAction(null);
          }}
          providerName={provider.name}
          onSubmit={(values) =>
            createCredential.mutate({
              providerId,
              data: { name: values.name, api_key: values.api_key },
            })
          }
          isPending={createCredential.isPending}
        />
      ) : null}
      {canManage ? (
        <CredentialPoolSheet
          open={poolSheetOpen}
          onOpenChange={(open) => {
            setCreatePoolOpen(open);
            if (!open && resourceAction === "configure-pool") void setResourceAction(null);
          }}
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
      ) : null}
      {canManage ? (
        <CreateModelOfferingSheet
          open={createModelOpen}
          onOpenChange={setCreateModelOpen}
          providerName={provider.name}
          onSubmit={(values) =>
            createModel.mutate({
              providerId,
              data: {
                provider_model_name: values.provider_model_name,
                ...(values.version ? { version: values.version } : {}),
                modality: combinedModality(values.input_modalities, values.output_modalities),
                input_modalities: values.input_modalities,
                output_modalities: values.output_modalities,
                context_window: values.context_window,
                input_price_per_million_tokens: dollarsToCents(
                  values.input_price_per_million_tokens,
                ),
                output_price_per_million_tokens: dollarsToCents(
                  values.output_price_per_million_tokens,
                ),
                cached_input_price_per_million_tokens: dollarsToCents(
                  values.cached_input_price_per_million_tokens,
                ),
                capabilities: capabilityListToRecord(values.capabilities),
              },
            })
          }
          isPending={createModel.isPending}
        />
      ) : null}
    </>
  );
}
