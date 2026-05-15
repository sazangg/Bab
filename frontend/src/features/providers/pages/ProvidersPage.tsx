import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryState } from "nuqs";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  MoreHorizontal,
  Pencil,
  Plug,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  ChevronDown,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch, type UseFormRegister } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import {
  createProviderApiV1ProvidersPost,
  createProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useCreateProviderApiV1ProvidersPost,
  useCreateProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useCreateModelOfferingApiV1ProvidersProviderIdOfferingsPost,
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useDeactivateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdDelete,
  useDeactivateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdDelete,
  useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
  useSyncModelOfferingsApiV1ProvidersProviderIdOfferingsSyncPost,
  useTestModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdTestPost,
  useTestProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdTestPost,
  useUpdateProviderCredentialApiV1ProvidersProviderIdCredentialsProviderCredentialIdPatch,
  useUpdateModelOfferingApiV1ProvidersProviderIdOfferingsModelOfferingIdPatch,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import type {
  ProviderCredentialResponse,
  ModelOfferingResponse,
  ProviderResponse,
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
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

const createSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  credential_routing_policy: z.enum([
    "priority",
    "round_robin",
    "least_recently_used",
    "health_based",
    "weighted",
    "fallback",
  ]),
});

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  credential_routing_policy: z.enum([
    "priority",
    "round_robin",
    "least_recently_used",
    "health_based",
    "weighted",
    "fallback",
  ]),
});

const providerCredentialSchema = z.object({
  name: z.string().min(1).max(255),
  api_key: z.string().min(1),
  priority: z.number().int().min(0),
});

type EditValues = z.infer<typeof editSchema>;
type ProviderCredentialValues = z.infer<typeof providerCredentialSchema>;
type RoutingPolicyValue = EditValues["credential_routing_policy"];

const modelModalities = ["text", "vision", "embedding", "image", "audio"];
const modelCapabilityOptions = ["chat", "embeddings", "vision", "tools", "json_mode", "streaming"];
const routingPolicyOptions = [
  {
    value: "priority",
    label: "Priority",
    description: "Always use the active credential with the lowest priority number.",
  },
  {
    value: "round_robin",
    label: "Round robin",
    description: "Rotate through active credentials by choosing the one used least recently.",
  },
  {
    value: "least_recently_used",
    label: "Least recently used",
    description: "Prefer the active credential with the oldest last-used timestamp.",
  },
  {
    value: "health_based",
    label: "Health based",
    description: "Prefer valid credentials before unchecked, degraded, or invalid credentials.",
  },
  {
    value: "weighted",
    label: "Weighted",
    description: "Randomly select a credential, with lower priority numbers receiving more weight.",
  },
  {
    value: "fallback",
    label: "Fallback",
    description: "Try credentials by priority and move to the next one on retryable upstream errors.",
  },
] as const;

const modelOfferingSchema = z.object({
  provider_model_name: z.string().min(1).max(255),
  alias: z.string().optional(),
  version: z.string().optional(),
  input_modalities: z.array(z.string()).min(1),
  output_modalities: z.array(z.string()).min(1),
  context_window: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(1).optional(),
  ),
  input_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  output_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  cached_input_price_per_million_tokens: z.preprocess(
    (value) => (value === "" || value === null || value === undefined ? undefined : Number(value)),
    z.number().int().min(0).optional(),
  ),
  capabilities: z.array(z.string()).default([]),
});

type ModelOfferingFormInput = z.input<typeof modelOfferingSchema>;
type ModelOfferingValues = z.output<typeof modelOfferingSchema>;

const providerPresets = [
  {
    id: "openai",
    name: "OpenAI",
    slug: "openai",
    baseUrl: "https://api.openai.com/v1",
    description: "Official OpenAI API for GPT models.",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    slug: "openrouter",
    baseUrl: "https://openrouter.ai/api/v1",
    description: "Multi-provider OpenAI-compatible model router.",
  },
  {
    id: "mistral",
    name: "Mistral AI",
    slug: "mistral",
    baseUrl: "https://api.mistral.ai/v1",
    description: "Mistral hosted models through their v1 API.",
  },
  {
    id: "groq",
    name: "Groq",
    slug: "groq",
    baseUrl: "https://api.groq.com/openai/v1",
    description: "Groq OpenAI-compatible inference endpoint.",
  },
] as const;

type ProviderPreset = (typeof providerPresets)[number];

type ProviderCatalogEntry = {
  key: string;
  name: string;
  slug?: string;
  baseUrl: string;
  description: string;
  provider?: ProviderResponse;
  preset?: ProviderPreset;
  isCustom: boolean;
};

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatRoutingPolicy(value: string) {
  return routingPolicyOptions.find((option) => option.value === value)?.label ?? value;
}

function formatCapability(value: unknown) {
  if (value === true) {
    return "Supported";
  }

  if (value === false) {
    return "Not declared";
  }

  return "Unknown";
}

function formatTokenPrice(value: number | null | undefined) {
  return value === null || value === undefined ? "Unset" : `${value.toLocaleString()} / 1M`;
}

function capabilityListToRecord(capabilities: string[]) {
  return Object.fromEntries(modelCapabilityOptions.map((item) => [item, capabilities.includes(item)]));
}

function capabilityRecordToList(capabilities: ModelOfferingResponse["capabilities"]) {
  return modelCapabilityOptions.filter((item) => capabilities?.[item] === true);
}

function combinedModality(inputModalities: string[], outputModalities: string[]) {
  return Array.from(new Set([...inputModalities, ...outputModalities])).join("+") || "text";
}

function formatModalities(modalities: string[]) {
  return modalities.length ? modalities.join(", ") : "Unknown";
}

function sanitizeCredentialValidationMessage(value?: string | null) {
  if (!value) return null;
  if (value.includes("401")) {
    return "The provider rejected this credential. Check the API key and provider account.";
  }
  if (value.includes("403")) {
    return "This credential is not authorized for the provider.";
  }
  if (value.includes("404")) {
    return "The provider models endpoint was not found. Check the provider base URL.";
  }
  if (value.includes("429")) {
    return "The provider rate limit was reached while testing this credential.";
  }
  if (value.includes("timeout") || value.includes("timed out")) {
    return "The provider did not respond before the request timed out.";
  }
  if (/\b5\d\d\b/.test(value)) {
    return "The provider returned a server error while testing this credential.";
  }
  return "Credential validation failed. Check the key and provider settings.";
}

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [addKeyTarget, setAddKeyTarget] = useState<ProviderCatalogEntry | null>(null);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);
  const [search, setSearch] = useState("");

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const knownEntries = providerPresets.map((preset) => {
    const provider = providers.find((item) => item.slug === preset.slug);
    return {
      key: preset.id,
      name: provider?.name ?? preset.name,
      slug: preset.slug,
      baseUrl: provider?.base_url ?? preset.baseUrl,
      description: preset.description,
      provider,
      preset,
      isCustom: false,
    } satisfies ProviderCatalogEntry;
  });
  const customEntries = providers
    .filter((provider) => !providerPresets.some((preset) => preset.slug === provider.slug))
    .map(
      (provider) =>
        ({
          key: provider.id,
          name: provider.name,
          slug: provider.slug ?? undefined,
          baseUrl: provider.base_url,
          description: "Custom OpenAI-compatible upstream provider.",
          provider,
          isCustom: true,
        }) satisfies ProviderCatalogEntry,
    );
  const catalogEntries = [...customEntries, ...knownEntries]
    .filter((entry) =>
      `${entry.name} ${entry.slug ?? ""} ${entry.baseUrl}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
    )
    .sort((a, b) => Number(Boolean(b.provider)) - Number(Boolean(a.provider)));

  const createMutation = useCreateProviderApiV1ProvidersPost({
    mutation: {
      onSuccess: async () => {
        setCreateOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateMutation = useUpdateProviderApiV1ProvidersProviderIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditTarget(null);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateMutation = useDeactivateProviderApiV1ProvidersProviderIdDelete({
    mutation: {
      onSuccess: async () => {
        setDeactivateTarget(null);
        await queryClient.invalidateQueries();
      },
    },
  });

  return (
    <>
      <PageHeader
        title="Providers"
        description="Add credentials to known providers, or register a custom OpenAI-compatible upstream."
        actions={
          <CreateProviderSheet
            open={createOpen}
            onOpenChange={setCreateOpen}
            onSubmit={(values) =>
              createMutation.mutate({
                data: {
                  name: values.name,
                  ...(values.slug ? { slug: values.slug } : {}),
                  base_url: values.base_url,
                  credential_routing_policy: values.credential_routing_policy,
                },
              })
            }
            isPending={createMutation.isPending}
            isError={createMutation.isError}
          />
        }
      />

      {providersQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading providers...</p>
      ) : (
        <div className="space-y-4">
          <div className="relative max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search providers..."
            />
          </div>
          {catalogEntries.length === 0 ? (
            <EmptyState
              icon={Plug}
              title="No providers match"
              description="Try another search, or add a custom provider."
              action={<Button onClick={() => setCreateOpen(true)}>Add custom provider</Button>}
            />
          ) : (
            <div className="space-y-3">
              {catalogEntries.map((entry) => (
                <ProviderCatalogRow
                  key={entry.key}
                  entry={entry}
                  onAddKey={() => setAddKeyTarget(entry)}
                  onEdit={() => entry.provider && setEditTarget(entry.provider)}
                  onDeactivate={() => entry.provider && setDeactivateTarget(entry.provider)}
                  onReactivate={() =>
                    entry.provider &&
                    updateMutation.mutate({
                      providerId: entry.provider.id,
                      data: { is_active: true },
                    })
                  }
                  isUpdating={updateMutation.isPending}
                />
              ))}
            </div>
          )}
        </div>
      )}

      <EditProviderSheet
        provider={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={(values) => {
          if (!editTarget) return;
          updateMutation.mutate({
            providerId: editTarget.id,
            data: {
              name: values.name,
              ...(values.slug ? { slug: values.slug } : {}),
              base_url: values.base_url,
              credential_routing_policy: values.credential_routing_policy,
            },
          });
        }}
        isPending={updateMutation.isPending}
      />
      <AddProviderCredentialDialog
        entry={addKeyTarget}
        onClose={() => setAddKeyTarget(null)}
        onCreated={async () => {
          setAddKeyTarget(null);
          await queryClient.invalidateQueries();
        }}
      />
      <Dialog
        open={Boolean(deactivateTarget)}
        onOpenChange={(open) => !open && setDeactivateTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate provider?</DialogTitle>
            <DialogDescription>
              Requests routed to {deactivateTarget?.name} will start failing. Project access rules
              remain intact.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={deactivateMutation.isPending}
              onClick={() =>
                deactivateTarget && deactivateMutation.mutate({ providerId: deactivateTarget.id })
              }
            >
              {deactivateMutation.isPending ? "Deactivating..." : "Deactivate"}
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

export function ProviderResourcesPanel({ provider }: { provider: ProviderResponse }) {
  return <ProviderResourcesContent provider={provider} />;
}

function ProviderCatalogRow({
  entry,
  onAddKey,
  onEdit,
  onDeactivate,
  onReactivate,
  isUpdating,
}: {
  entry: ProviderCatalogEntry;
  onAddKey: () => void;
  onEdit: () => void;
  onDeactivate: () => void;
  onReactivate: () => void;
  isUpdating: boolean;
}) {
  const providerId = entry.provider?.id ?? "";
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    providerId,
    {
      query: { enabled: Boolean(providerId) },
    },
  );
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const activeCredentialCount = credentials.filter((credential) => credential.is_active).length;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors hover:bg-muted/30",
        entry.provider && !entry.provider.is_active && "opacity-60",
      )}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <Link
          className="min-w-0 flex-1 space-y-2"
          to={entry.provider ? `/providers/${entry.provider.id}` : "#"}
          onClick={(event) => {
            if (!entry.provider) event.preventDefault();
          }}
        >
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-background text-sm font-semibold">
              {entry.name.slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-medium">{entry.name}</h2>
                {entry.provider ? (
                  <StatusBadge variant={entry.provider.is_active ? "active" : "inactive"}>
                    {entry.provider.is_active ? "Configured" : "Disabled"}
                  </StatusBadge>
                ) : (
                  <StatusBadge variant="inactive">Not configured</StatusBadge>
                )}
                {activeCredentialCount > 0 ? (
                  <span className="text-xs text-muted-foreground">
                    {activeCredentialCount} active{" "}
                    {activeCredentialCount === 1 ? "credential" : "credentials"}
                  </span>
                ) : null}
                {entry.provider ? (
                  <span className="text-xs text-muted-foreground">
                    {formatRoutingPolicy(entry.provider.credential_routing_policy)}
                  </span>
                ) : null}
              </div>
              <p className="text-sm text-muted-foreground">{entry.description}</p>
            </div>
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground">{entry.baseUrl}</p>
        </Link>

        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" onClick={onAddKey}>
            <Plus />
            Add credential
          </Button>
          {entry.provider ? (
            <>
              <Button asChild size="sm" variant="outline">
                <Link to={`/providers/${entry.provider.id}`}>Open</Link>
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label="Provider actions">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={onEdit}>
                    <Pencil className="mr-2 size-4" />
                    Edit provider
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={onDeactivate}
                    disabled={!entry.provider.is_active}
                    variant="destructive"
                  >
                    <Power className="mr-2 size-4" />
                    Deactivate
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={onReactivate}
                    disabled={entry.provider.is_active || isUpdating}
                  >
                    <RotateCcw className="mr-2 size-4" />
                    Reactivate
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ProviderResourcesContent({ provider }: { provider: ProviderResponse }) {
  const queryClient = useQueryClient();
  const providerId = provider.id;
  const [tab, setTab] = useQueryState("tab", { defaultValue: "credentials" });
  const activeTab = tab === "models" ? "models" : "credentials";
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
  const [createModelOpen, setCreateModelOpen] = useState(false);
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
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const modelsPage =
    modelsQuery.data?.status === 200
      ? modelsQuery.data.data
      : { items: [], total: 0, limit: modelPageSize, offset: modelOffset };

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
  const [testResult, setTestResult] = useState<{
    providerCredentialId: string;
    message: string;
    status: "valid" | "invalid";
  } | null>(null);
  const [modelTestResult, setModelTestResult] = useState<{
    modelOfferingId: string;
    message: string;
    status: "valid" | "invalid";
  } | null>(null);
  const hasActiveCredential = credentials.some((credential) => credential.is_active);

  function handleTestCredential(providerCredential: ProviderCredentialResponse) {
    setTestResult(null);
    testCredential.mutate(
      { providerId, providerCredentialId: providerCredential.id },
      {
        onSuccess: (response) => {
          if (response.status !== 200) {
            setTestResult({
              providerCredentialId: providerCredential.id,
              message: "Credential validation failed. Check the key and provider settings.",
              status: "invalid",
            });
            return;
          }

          const message =
            response.data.health_status === "valid"
              ? "Credential test succeeded."
              : (sanitizeCredentialValidationMessage(response.data.last_validation_error) ??
                "Credential test failed.");
          setTestResult({
            providerCredentialId: providerCredential.id,
            message,
            status: response.data.health_status === "valid" ? "valid" : "invalid",
          });
        },
        onError: () => {
          setTestResult({
            providerCredentialId: providerCredential.id,
            message: "Credential validation failed. Check the key and provider settings.",
            status: "invalid",
          });
        },
      },
    );
  }

  function handleTestModel(model: ModelOfferingResponse) {
    setModelTestResult(null);
    testModel.mutate(
      { providerId, modelOfferingId: model.id },
      {
        onSuccess: (response) => {
          if (response.status !== 200) {
            setModelTestResult({
              modelOfferingId: model.id,
              message: "Model validation failed. Check the model and provider credentials.",
              status: "invalid",
            });
            return;
          }

          const message =
            response.data.health_status === "valid"
              ? "Model test succeeded."
              : (sanitizeCredentialValidationMessage(response.data.last_validation_error) ??
                "Model test failed.");
          setModelTestResult({
            modelOfferingId: model.id,
            message,
            status: response.data.health_status === "valid" ? "valid" : "invalid",
          });
        },
        onError: () => {
          setModelTestResult({
            modelOfferingId: model.id,
            message: "Model validation failed. Check the model and provider credentials.",
            status: "invalid",
          });
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
            Credentials authenticate upstream requests. Models define what this provider can serve.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setTab} className="gap-5">
            <TabsList>
              <TabsTrigger value="credentials">Credentials</TabsTrigger>
              <TabsTrigger value="models">Models</TabsTrigger>
            </TabsList>
            <TabsContent value="credentials" className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 className="text-base font-medium">Credentials</h3>
                  <p className="text-sm text-muted-foreground">
                    Credentials are encrypted. Provider routing strategy decides how active
                    credentials are selected.
                  </p>
                </div>
                <Button size="sm" onClick={() => setCreateCredentialOpen(true)}>
                  <Plus />
                  Add credential
                </Button>
              </div>
              <ResourceKeyTable
                providerId={providerId}
                credentials={credentials}
                isLoading={credentialsQuery.isPending || credentialsQuery.isFetching}
                isError={credentialsQuery.isError}
                isTesting={testCredential.isPending}
                testResult={testResult}
                onUpdate={(credential, values) =>
                  updateCredential.mutate({
                    providerId,
                    providerCredentialId: credential.id,
                    data: values,
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
                testResult={modelTestResult}
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
                      input_price_per_million_tokens:
                        values.input_price_per_million_tokens ?? null,
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
              priority: values.priority,
            },
          })
        }
        isPending={createCredential.isPending}
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
              cached_input_price_per_million_tokens:
                values.cached_input_price_per_million_tokens,
              capabilities: capabilityListToRecord(values.capabilities),
            },
          })
        }
        isPending={createModel.isPending}
      />
    </>
  );
}

function ResourceKeyTable({
  providerId,
  credentials,
  isLoading,
  isError,
  isTesting,
  testResult,
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
  testResult: {
    providerCredentialId: string;
    message: string;
    status: "valid" | "invalid";
  } | null;
  onUpdate: (
    credential: ProviderCredentialResponse,
    values: { name: string; priority: number },
  ) => void;
  onRotate: (credential: ProviderCredentialResponse, apiKey: string) => void;
  onDeactivate: (credential: ProviderCredentialResponse) => void;
  onReactivate: (credential: ProviderCredentialResponse) => void;
  onTest: (credential: ProviderCredentialResponse) => void;
}) {
  const sortedCredentials = [...credentials].sort(
    (a, b) =>
      Number(b.is_active) - Number(a.is_active) ||
      a.priority - b.priority ||
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  const syncCredential = sortedCredentials.find((credential) => credential.is_active);
  const [editCredential, setEditCredential] = useState<ProviderCredentialResponse | null>(null);
  const [rotateCredential, setRotateCredential] = useState<ProviderCredentialResponse | null>(null);
  const [apiKey, setApiKey] = useState("");

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Credential</TableHead>
            <TableHead>Prefix</TableHead>
            <TableHead>Priority</TableHead>
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
              <TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">
                Loading credentials...
              </TableCell>
            </TableRow>
          ) : null}
          {isError ? (
            <TableRow>
              <TableCell colSpan={8} className="py-8 text-center text-sm text-destructive">
                Credentials could not be loaded.
              </TableCell>
            </TableRow>
          ) : null}
          {!isLoading && !isError && sortedCredentials.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">
                No credentials added yet.
              </TableCell>
            </TableRow>
          ) : null}
          {sortedCredentials.map((credential) => (
            <TableRow key={credential.id}>
              <TableCell className="font-medium">
                <div>{credential.name}</div>
                <p className="text-xs text-muted-foreground">
                  Created by {credential.created_by ?? "system"}
                </p>
                {syncCredential?.id === credential.id ? (
                  <p className="text-xs text-muted-foreground">Used first for model sync</p>
                ) : null}
                {testResult?.providerCredentialId === credential.id ? (
                  <p
                    className={
                      testResult.status === "valid"
                        ? "text-xs text-emerald-600"
                        : "text-xs text-destructive"
                    }
                  >
                    {testResult.message}
                  </p>
                ) : credential.last_validation_error ? (
                  <p className="text-xs text-destructive">
                    {sanitizeCredentialValidationMessage(credential.last_validation_error)}
                  </p>
                ) : null}
              </TableCell>
              <TableCell className="font-mono text-xs">{credential.key_prefix}</TableCell>
              <TableCell>{credential.priority}</TableCell>
              <TableCell>
                <StatusBadge
                  variant={
                    credential.health_status === "valid"
                      ? "active"
                      : credential.health_status === "unchecked"
                        ? "inactive"
                        : "error"
                  }
                >
                  {credential.health_status}
                </StatusBadge>
              </TableCell>
              <TableCell>
                <StatusBadge variant={credential.is_active ? "active" : "inactive"}>
                  {credential.is_active ? "Active" : "Disabled"}
                </StatusBadge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatDateTime(credential.created_at)}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {credential.last_successful_request_at
                  ? formatDateTime(credential.last_successful_request_at)
                  : credential.last_used_at
                    ? formatDateTime(credential.last_used_at)
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
                    <Trash2 />
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
          ))}
        </TableBody>
      </Table>
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
            <DialogTitle>Rotate credential</DialogTitle>
            <DialogDescription>Paste the replacement upstream API key.</DialogDescription>
          </DialogHeader>
          <Input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
          <DialogFooter>
            <Button
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
  onSubmit: (values: { name: string; priority: number }) => void;
}) {
  const form = useForm<{ name: string; priority: number }>({
    resolver: zodResolver(
      z.object({
        name: z.string().min(1).max(255),
        priority: z.number().int().min(0),
      }),
    ),
    defaultValues: { name: "", priority: 100 },
  });

  useEffect(() => {
    if (providerCredential) {
      form.reset({
        name: providerCredential.name,
        priority: providerCredential.priority,
      });
    }
  }, [providerCredential, form]);

  return (
    <Sheet open={Boolean(providerCredential)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit credential</SheetTitle>
          <SheetDescription>
            Rename this credential or change routing priority. Use rotate to replace the secret.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-key-name">Name</Label>
            <Input id="edit-provider-key-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-key-priority">Routing priority</Label>
            <Input
              id="edit-provider-key-priority"
              type="number"
              {...form.register("priority", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Active credentials are tried first. Lower numbers win within active credentials.
            </p>
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
    defaultValues: { name: "", api_key: "", priority: 100 },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        name: `${providerName} credential`,
        api_key: "",
        priority: 100,
      });
    }
  }, [open, providerName, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add credential</SheetTitle>
          <SheetDescription>
            Add an encrypted upstream API key for {providerName}. Lower routing priority wins.
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
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-key-priority">Routing priority</Label>
            <Input
              id="detail-provider-key-priority"
              type="number"
              {...form.register("priority", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Lower numbers are preferred when multiple active credentials exist for this provider.
            </p>
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

function RoutingPolicyField({
  value,
  onValueChange,
  disabled = false,
}: {
  value: string;
  onValueChange: (value: RoutingPolicyValue) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="provider-key-routing-policy">Routing strategy</Label>
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={disabled}>
          <Button
            id="provider-key-routing-policy"
            type="button"
            variant="outline"
            className="w-full justify-between"
          >
            {formatRoutingPolicy(value)}
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-80">
          {routingPolicyOptions.map((option) => (
            <DropdownMenuItem
              key={option.value}
              className="flex flex-col items-start gap-0.5"
              onSelect={() => onValueChange(option.value)}
            >
              <span>{option.label}</span>
              <span className="text-xs text-muted-foreground">{option.description}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
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
    <div className="grid gap-3 md:grid-cols-3">
      <div className="space-y-1.5">
        <Label htmlFor={`${prefix}-provider-model-input-price`}>Input price / 1M</Label>
        <Input
          id={`${prefix}-provider-model-input-price`}
          type="number"
          min={0}
          placeholder="0"
          {...register("input_price_per_million_tokens")}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${prefix}-provider-model-output-price`}>Output price / 1M</Label>
        <Input
          id={`${prefix}-provider-model-output-price`}
          type="number"
          min={0}
          placeholder="0"
          {...register("output_price_per_million_tokens")}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${prefix}-provider-model-cached-price`}>Cached input / 1M</Label>
        <Input
          id={`${prefix}-provider-model-cached-price`}
          type="number"
          min={0}
          placeholder="0"
          {...register("cached_input_price_per_million_tokens")}
        />
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
  testResult,
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
  testResult: {
    modelOfferingId: string;
    message: string;
    status: "valid" | "invalid";
  } | null;
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
      output_modalities: editModel.output_modalities?.length ? editModel.output_modalities : ["text"],
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

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {models.map((model) => (
            <Card key={model.id} size="sm" className={!model.is_active ? "opacity-60" : undefined}>
              <CardHeader>
                <CardTitle className="truncate font-mono text-sm">
                  {model.provider_model_name}
                </CardTitle>
                <CardDescription>
                  {model.alias ? `Alias: ${model.alias}` : "No alias configured"}
                </CardDescription>
                <CardAction>
                  <StatusBadge variant={model.is_active ? "active" : "inactive"}>
                    {model.is_active ? "Active" : "Disabled"}
                  </StatusBadge>
                </CardAction>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-3">
                  <ModelFact label="Input" value={formatModalities(model.input_modalities)} />
                  <ModelFact label="Output" value={formatModalities(model.output_modalities)} />
                  <ModelFact
                    label="Context"
                    value={model.context_window ? model.context_window.toLocaleString() : "Unknown"}
                  />
                  <ModelFact label="Version" value={model.version ?? "Unknown"} />
                  <ModelFact
                    label="Streaming"
                    value={formatCapability(model.capabilities?.streaming)}
                  />
                  <ModelFact
                    label="Input price"
                    value={formatTokenPrice(model.input_price_per_million_tokens)}
                  />
                  <ModelFact
                    label="Output price"
                    value={formatTokenPrice(model.output_price_per_million_tokens)}
                  />
                  <ModelFact label="Usage" value="Pending" />
                </div>
                {testResult?.modelOfferingId === model.id ? (
                  <p
                    className={cn(
                      "rounded-md border p-2 text-xs",
                      testResult.status === "valid"
                        ? "text-muted-foreground"
                        : "text-destructive",
                    )}
                  >
                    {testResult.message}
                  </p>
                ) : null}
                <div className="flex justify-end gap-1">
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
                    onClick={() => {
                      setEditModel(model);
                    }}
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
                      <Trash2 />
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
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

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
          <form className="grid gap-4 px-4" onSubmit={editForm.handleSubmit((values) => {
            if (editModel) onUpdate(editModel, values);
            setEditModel(null);
          })}>
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

function ModelFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
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
              const next = checked
                ? [...values, item]
                : values.filter((value) => value !== item);
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
              const next = checked
                ? [...values, item]
                : values.filter((value) => value !== item);
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

function AddProviderCredentialDialog({
  entry,
  onClose,
  onCreated,
}: {
  entry: ProviderCatalogEntry | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);
  const form = useForm<ProviderCredentialValues>({
    resolver: zodResolver(providerCredentialSchema),
    defaultValues: { name: "", api_key: "", priority: 100 },
  });

  useEffect(() => {
    if (entry) {
      form.reset({
        name: `${entry.name} credential`,
        api_key: "",
        priority: 100,
      });
    }
  }, [entry, form]);

  const submit = form.handleSubmit(async (values) => {
    if (!entry) return;

    setIsPending(true);
    setIsError(false);
    try {
      let providerId = entry.provider?.id;
      if (!providerId) {
        const response = await createProviderApiV1ProvidersPost({
          name: entry.name,
          ...(entry.slug ? { slug: entry.slug } : {}),
          base_url: entry.baseUrl,
        });
        if (response.status !== 201) {
          throw new Error("Provider was not created.");
        }
        providerId = response.data.id;
      }

      const keyResponse = await createProviderCredentialApiV1ProvidersProviderIdCredentialsPost(
        providerId,
        {
          name: values.name,
          api_key: values.api_key,
          priority: values.priority,
        },
      );
      if (keyResponse.status !== 201) {
        throw new Error("Credential was not created.");
      }
      await onCreated();
    } catch {
      setIsError(true);
    } finally {
      setIsPending(false);
    }
  });

  return (
    <Sheet open={Boolean(entry)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add credential</SheetTitle>
          <SheetDescription>
            {entry
              ? `Add an encrypted upstream API key for ${entry.name}.`
              : "Add an encrypted upstream API key."}
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-name">Name</Label>
            <Input id="provider-key-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-secret">API key</Label>
            <Input
              id="provider-key-secret"
              type="password"
              autoComplete="new-password"
              {...form.register("api_key")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-priority">Routing priority</Label>
            <Input
              id="provider-key-priority"
              type="number"
              {...form.register("priority", { valueAsNumber: true })}
            />
            <p className="text-xs text-muted-foreground">
              Lower numbers are preferred when multiple active credentials exist for this provider.
            </p>
          </div>
          {isError ? <p className="text-sm text-destructive">Credential was not added.</p> : null}
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={submit}>
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

function CreateProviderSheet({
  open,
  onOpenChange,
  onSubmit,
  isPending,
  isError,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: CreateValues) => void;
  isPending: boolean;
  isError: boolean;
}) {
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      name: "",
      slug: "",
      base_url: "",
      credential_routing_policy: "priority",
    },
  });
  const routingPolicy = useWatch({ control: form.control, name: "credential_routing_policy" });

  useEffect(() => {
    if (open) {
      form.reset({
        name: "",
        slug: "",
        base_url: "",
        credential_routing_policy: "priority",
      });
    }
  }, [open, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button>
          <Plus />
          Add custom provider
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add custom provider</SheetTitle>
          <SheetDescription>
            Use this only for providers missing from the catalog. Known providers can be configured
            directly with Add credential.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" autoComplete="off" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="provider-name">Name</Label>
            <Input id="provider-name" autoFocus placeholder="Acme AI" {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-slug">Slug</Label>
            <Input id="provider-slug" placeholder="acme-ai" {...form.register("slug")} />
            <p className="text-xs text-muted-foreground">
              Optional provider hint for proxy requests.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-base-url">Base URL</Label>
            <Input
              id="provider-base-url"
              autoComplete="off"
              placeholder="https://api.example.com/v1"
              {...form.register("base_url")}
            />
            {form.formState.errors.base_url ? (
              <p className="text-xs text-destructive">{form.formState.errors.base_url.message}</p>
            ) : null}
          </div>
          <RoutingPolicyField
            value={routingPolicy}
            onValueChange={(value) => form.setValue("credential_routing_policy", value)}
          />
          {isError ? <p className="text-sm text-destructive">Provider was not created.</p> : null}
        </form>
        <SheetFooter>
          <Button type="submit" disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Adding..." : "Add custom provider"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function EditProviderSheet({
  provider,
  onClose,
  onSubmit,
  isPending,
}: {
  provider: ProviderResponse | null;
  onClose: () => void;
  onSubmit: (values: EditValues) => void;
  isPending: boolean;
}) {
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      name: "",
      slug: "",
      base_url: "",
      credential_routing_policy: "priority",
    },
  });
  const routingPolicy = useWatch({ control: form.control, name: "credential_routing_policy" });

  useEffect(() => {
    if (provider) {
      form.reset({
        name: provider.name,
        slug: provider.slug ?? "",
        base_url: provider.base_url,
        credential_routing_policy: provider.credential_routing_policy as RoutingPolicyValue,
      });
    }
  }, [provider, form]);

  return (
    <Sheet open={Boolean(provider)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit provider</SheetTitle>
          <SheetDescription>
            Credentials are managed separately on the provider detail page.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-name">Name</Label>
            <Input id="edit-provider-name" {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-slug">Slug</Label>
            <Input id="edit-provider-slug" {...form.register("slug")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-base-url">Base URL</Label>
            <Input id="edit-provider-base-url" {...form.register("base_url")} />
          </div>
          <RoutingPolicyField
            value={routingPolicy}
            onValueChange={(value) => form.setValue("credential_routing_policy", value)}
          />
        </form>
        <SheetFooter>
          <Button type="submit" disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Saving..." : "Save changes"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
