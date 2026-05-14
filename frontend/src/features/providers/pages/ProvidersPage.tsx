import { zodResolver } from "@hookform/resolvers/zod";
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
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
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
  DropdownMenuContent,
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

const createSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
});

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
});

const providerCredentialSchema = z.object({
  name: z.string().min(1).max(255),
  api_key: z.string().min(1),
  priority: z.number().int().min(0),
});

type ProviderCredentialValues = z.infer<typeof providerCredentialSchema>;

const modelOfferingSchema = z.object({
  provider_model_name: z.string().min(1).max(255),
  alias: z.string().optional(),
});

type ModelOfferingValues = z.infer<typeof modelOfferingSchema>;

type EditValues = z.infer<typeof editSchema>;

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
    <div className="rounded-lg border p-4 transition-colors hover:bg-muted/30">
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

function ProviderFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

function ProviderResourcesContent({ provider }: { provider: ProviderResponse }) {
  const queryClient = useQueryClient();
  const providerId = provider.id;
  const [createCredentialOpen, setCreateCredentialOpen] = useState(false);
  const [createModelOpen, setCreateModelOpen] = useState(false);
  const credentialsQuery = useListProviderCredentialsApiV1ProvidersProviderIdCredentialsGet(
    providerId,
    {
      query: { enabled: Boolean(providerId) },
    },
  );
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const credentials = credentialsQuery.data?.status === 200 ? credentialsQuery.data.data : [];
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data : [];

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
  const [testResult, setTestResult] = useState<{
    providerCredentialId: string;
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

  return (
    <>
      <div className="space-y-6 overflow-y-auto pb-6">
        <section className="grid gap-3 rounded-lg border p-4 md:grid-cols-4">
          <ProviderFact label="Integration" value={provider.supported_integration} />
          <ProviderFact label="Timeout" value={`${provider.request_timeout_seconds ?? 30}s`} />
          <ProviderFact
            label="Max body"
            value={
              provider.max_body_bytes
                ? `${Math.round(provider.max_body_bytes / 1024)} KB`
                : "Default"
            }
          />
          <ProviderFact
            label="Concurrency"
            value={provider.max_concurrent_requests?.toString() ?? "Default"}
          />
        </section>
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Credentials</h3>
              <p className="text-xs text-muted-foreground">
                Credentials are encrypted. Routing priority decides which active credential is tried
                first.
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
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Models</h3>
              <p className="text-xs text-muted-foreground">
                Alias is optional and scoped to this provider.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setCreateModelOpen(true)}>
                <Plus />
                Add offering
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!providerId || !hasActiveCredential || syncModels.isPending}
                onClick={() => providerId && syncModels.mutate({ providerId })}
                title={
                  !hasActiveCredential
                    ? "Add an active credential before syncing models."
                    : undefined
                }
              >
                <RefreshCw />
                Sync
              </Button>
            </div>
          </div>
          <ResourceModelTable
            providerId={providerId}
            models={models}
            isLoading={modelsQuery.isPending || modelsQuery.isFetching}
            isError={modelsQuery.isError}
            onAlias={(model, alias) =>
              updateModel.mutate({
                providerId,
                modelOfferingId: model.id,
                data: { alias: alias || null },
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
          />
        </section>
      </div>
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
      form.reset({ name: providerCredential.name, priority: providerCredential.priority });
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
    if (open) form.reset({ name: `${providerName} credential`, api_key: "", priority: 100 });
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
  const form = useForm<ModelOfferingValues>({
    resolver: zodResolver(modelOfferingSchema),
    defaultValues: { provider_model_name: "", alias: "" },
  });

  useEffect(() => {
    if (open) form.reset({ provider_model_name: "", alias: "" });
  }, [open, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add model offering</SheetTitle>
          <SheetDescription>
            Register a model name exposed by {providerName}. Alias is optional and provider-scoped.
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

function ResourceModelTable({
  providerId,
  models,
  isLoading,
  isError,
  onAlias,
  onDeactivate,
  onReactivate,
}: {
  providerId: string;
  models: ModelOfferingResponse[];
  isLoading: boolean;
  isError: boolean;
  onAlias: (model: ModelOfferingResponse, alias: string) => void;
  onDeactivate: (model: ModelOfferingResponse) => void;
  onReactivate: (model: ModelOfferingResponse) => void;
}) {
  const [editModel, setEditModel] = useState<ModelOfferingResponse | null>(null);
  const [alias, setAlias] = useState("");
  const sortedModels = [...models].sort(
    (a, b) =>
      Number(b.is_active) - Number(a.is_active) ||
      a.provider_model_name.localeCompare(b.provider_model_name),
  );

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Provider model</TableHead>
            <TableHead>Alias</TableHead>
            <TableHead>Modality</TableHead>
            <TableHead>Context</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-[1%]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                Loading model offerings...
              </TableCell>
            </TableRow>
          ) : null}
          {isError ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-destructive">
                Model offerings could not be loaded.
              </TableCell>
            </TableRow>
          ) : null}
          {!isLoading && !isError && sortedModels.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                No model offerings added yet.
              </TableCell>
            </TableRow>
          ) : null}
          {sortedModels.map((model) => (
            <TableRow key={model.id}>
              <TableCell>
                <div className="font-mono text-xs">{model.provider_model_name}</div>
                <div className="text-xs text-muted-foreground">
                  {model.version ?? "Unversioned"}
                </div>
              </TableCell>
              <TableCell>{model.alias || "—"}</TableCell>
              <TableCell>{model.modality}</TableCell>
              <TableCell>
                {model.context_window ? model.context_window.toLocaleString() : "—"}
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
                  onClick={() => {
                    setEditModel(model);
                    setAlias(model.alias ?? "");
                  }}
                >
                  <Pencil />
                </Button>
                {model.is_active ? (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    disabled={!providerId}
                    onClick={() => onDeactivate(model)}
                  >
                    <Trash2 />
                  </Button>
                ) : (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    disabled={!providerId}
                    onClick={() => onReactivate(model)}
                  >
                    <RotateCcw />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog open={Boolean(editModel)} onOpenChange={(open) => !open && setEditModel(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit alias</DialogTitle>
            <DialogDescription>Aliases are unique only within this provider.</DialogDescription>
          </DialogHeader>
          <Input value={alias} onChange={(event) => setAlias(event.target.value)} />
          <DialogFooter>
            <Button
              disabled={!editModel}
              onClick={() => {
                if (editModel) onAlias(editModel, alias);
                setEditModel(null);
              }}
            >
              Save
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
      form.reset({ name: `${entry.name} credential`, api_key: "", priority: 100 });
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
    },
  });

  useEffect(() => {
    if (open) form.reset({ name: "", slug: "", base_url: "" });
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

function EditProviderSheet({
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
    defaultValues: { name: "", slug: "", base_url: "" },
  });

  useEffect(() => {
    if (provider) {
      form.reset({
        name: provider.name,
        slug: provider.slug ?? "",
        base_url: provider.base_url,
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
