import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
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
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import {
  createProviderApiV1ProvidersPost,
  createProviderKeyApiV1ProvidersProviderIdKeysPost,
  useCreateProviderApiV1ProvidersPost,
  useCreateProviderKeyApiV1ProvidersProviderIdKeysPost,
  useCreateProviderModelApiV1ProvidersProviderIdModelsPost,
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useDeactivateProviderKeyApiV1ProvidersProviderIdKeysProviderKeyIdDelete,
  useDeactivateProviderModelApiV1ProvidersProviderIdModelsProviderModelIdDelete,
  useListProviderKeysApiV1ProvidersProviderIdKeysGet,
  useListProviderModelsApiV1ProvidersProviderIdModelsGet,
  useListProvidersApiV1ProvidersGet,
  useSyncProviderModelsApiV1ProvidersProviderIdModelsSyncPost,
  useUpdateProviderKeyApiV1ProvidersProviderIdKeysProviderKeyIdPatch,
  useUpdateProviderModelApiV1ProvidersProviderIdModelsProviderModelIdPatch,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import type {
  ProviderKeyResponse,
  ProviderModelResponse,
  ProviderResponse,
  SubscriptionProviderKeyResponse,
  SubscriptionResponse,
} from "@/shared/api/generated/schemas";
import {
  useAttachProviderKeyToSubscriptionApiV1SubscriptionsSubscriptionIdProviderKeysPost,
  useCreateSubscriptionApiV1SubscriptionsPost,
  useListSubscriptionProviderKeysApiV1SubscriptionsSubscriptionIdProviderKeysGet,
} from "@/shared/api/generated/subscriptions/subscriptions";
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
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { Textarea } from "@/components/ui/textarea";

const createSchema = z.object({
  provider_preset: z.string().optional(),
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  api_key: z.string().optional(),
});

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().optional(),
  base_url: z.url(),
  api_key: z.string().optional(),
});

const providerKeySchema = z.object({
  name: z.string().min(1).max(255),
  api_key: z.string().min(1),
  priority: z.number().int().min(0),
});

type ProviderKeyValues = z.infer<typeof providerKeySchema>;

const providerModelSchema = z.object({
  provider_model_name: z.string().min(1).max(255),
  alias: z.string().optional(),
});

type ProviderModelValues = z.infer<typeof providerModelSchema>;

const subscriptionSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().optional(),
});

type SubscriptionValues = z.infer<typeof subscriptionSchema>;

const subscriptionProviderKeySchema = z.object({
  provider_id: z.string().min(1, "Pick a provider"),
  provider_key_id: z.string().min(1, "Pick a provider key"),
  priority: z.number().int().min(0),
});

type SubscriptionProviderKeyValues = z.infer<typeof subscriptionProviderKeySchema>;

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
  {
    id: "custom",
    name: "Custom OpenAI-compatible",
    slug: "",
    baseUrl: "",
    description: "Add another compatible upstream manually.",
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

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [addKeyTarget, setAddKeyTarget] = useState<ProviderCatalogEntry | null>(null);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);
  const [search, setSearch] = useState("");

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const knownEntries = providerPresets
    .filter((preset) => preset.id !== "custom")
    .map((preset) => {
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
        description="Add API keys to known providers, or register a custom OpenAI-compatible upstream."
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
                  ...(values.api_key ? { api_key: values.api_key } : {}),
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
              ...(values.api_key ? { api_key: values.api_key } : {}),
            },
          });
        }}
        isPending={updateMutation.isPending}
      />
      <AddProviderKeyDialog
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
  const keysQuery = useListProviderKeysApiV1ProvidersProviderIdKeysGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const activeKeyCount = keys.filter((key) => key.is_active).length;

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
                {activeKeyCount > 0 ? (
                  <span className="text-xs text-muted-foreground">
                    {activeKeyCount} active {activeKeyCount === 1 ? "key" : "keys"}
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
            Add key
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
  const keysQuery = useListProviderKeysApiV1ProvidersProviderIdKeysGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const modelsQuery = useListProviderModelsApiV1ProvidersProviderIdModelsGet(providerId, {
    query: { enabled: Boolean(providerId) },
  });
  const keys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data : [];

  const keyForm = useForm<ProviderKeyValues>({
    resolver: zodResolver(providerKeySchema),
    defaultValues: { name: "", api_key: "", priority: 100 },
  });
  const modelForm = useForm<ProviderModelValues>({
    resolver: zodResolver(providerModelSchema),
    defaultValues: { provider_model_name: "", alias: "" },
  });

  const createKey = useCreateProviderKeyApiV1ProvidersProviderIdKeysPost({
    mutation: {
      onSuccess: async () => {
        keyForm.reset({ name: "", api_key: "", priority: 100 });
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateKey = useUpdateProviderKeyApiV1ProvidersProviderIdKeysProviderKeyIdPatch({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const deactivateKey = useDeactivateProviderKeyApiV1ProvidersProviderIdKeysProviderKeyIdDelete({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const createModel = useCreateProviderModelApiV1ProvidersProviderIdModelsPost({
    mutation: {
      onSuccess: async () => {
        modelForm.reset({ provider_model_name: "", alias: "" });
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateModel = useUpdateProviderModelApiV1ProvidersProviderIdModelsProviderModelIdPatch({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });
  const deactivateModel =
    useDeactivateProviderModelApiV1ProvidersProviderIdModelsProviderModelIdDelete({
      mutation: { onSuccess: async () => queryClient.invalidateQueries() },
    });
  const syncModels = useSyncProviderModelsApiV1ProvidersProviderIdModelsSyncPost({
    mutation: { onSuccess: async () => queryClient.invalidateQueries() },
  });

  return (
    <>
      <div className="space-y-1">
        <h2 className="text-base font-semibold">{provider.name} resources</h2>
        <p className="text-sm text-muted-foreground">
          Manage provider API keys and the models available through subscriptions.
        </p>
      </div>
      <div className="space-y-6 overflow-y-auto pb-6">
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">API keys</h3>
                <p className="text-xs text-muted-foreground">
                  Keys are encrypted and can be attached to subscriptions.
                </p>
              </div>
            </div>
            <form
              className="grid gap-2 md:grid-cols-[1fr_1fr_90px_auto]"
              onSubmit={keyForm.handleSubmit((values) =>
                providerId
                  ? createKey.mutate({
                      providerId,
                      data: {
                        name: values.name,
                        api_key: values.api_key,
                        priority: values.priority,
                      },
                    })
                  : undefined,
              )}
            >
              <Input placeholder="Production" {...keyForm.register("name")} />
              <Input type="password" placeholder="sk-..." {...keyForm.register("api_key")} />
              <Input type="number" {...keyForm.register("priority", { valueAsNumber: true })} />
              <Button type="submit" disabled={createKey.isPending || !providerId}>
                <Plus />
                Add
              </Button>
            </form>
            <ResourceKeyTable
              providerId={providerId}
              keys={keys}
              onRotate={(key, apiKey) =>
                updateKey.mutate({
                  providerId,
                  providerKeyId: key.id,
                  data: { api_key: apiKey },
                })
              }
              onDeactivate={(key) =>
                deactivateKey.mutate({ providerId, providerKeyId: key.id })
              }
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
              <Button
                size="sm"
                variant="outline"
                disabled={!providerId || syncModels.isPending}
                onClick={() => providerId && syncModels.mutate({ providerId })}
              >
                <RefreshCw />
                Sync
              </Button>
            </div>
            <form
              className="grid gap-2 md:grid-cols-[1fr_1fr_auto]"
              onSubmit={modelForm.handleSubmit((values) =>
                providerId
                  ? createModel.mutate({
                      providerId,
                      data: {
                        provider_model_name: values.provider_model_name,
                        ...(values.alias ? { alias: values.alias } : {}),
                      },
                    })
                  : undefined,
              )}
            >
              <Input placeholder="gpt-5.4-mini" {...modelForm.register("provider_model_name")} />
              <Input placeholder="fast" {...modelForm.register("alias")} />
              <Button type="submit" disabled={createModel.isPending || !providerId}>
                <Plus />
                Add
              </Button>
            </form>
            <ResourceModelTable
              providerId={providerId}
              models={models}
              onAlias={(model, alias) =>
                updateModel.mutate({
                  providerId,
                  providerModelId: model.id,
                  data: { alias: alias || null },
                })
              }
              onDeactivate={(model) =>
                deactivateModel.mutate({ providerId, providerModelId: model.id })
              }
            />
          </section>
      </div>
    </>
  );
}

function ResourceKeyTable({
  providerId,
  keys,
  onRotate,
  onDeactivate,
}: {
  providerId: string;
  keys: ProviderKeyResponse[];
  onRotate: (key: ProviderKeyResponse, apiKey: string) => void;
  onDeactivate: (key: ProviderKeyResponse) => void;
}) {
  const [rotateKey, setRotateKey] = useState<ProviderKeyResponse | null>(null);
  const [apiKey, setApiKey] = useState("");

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Prefix</TableHead>
            <TableHead>Priority</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-[1%]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => (
            <TableRow key={key.id}>
              <TableCell className="font-medium">{key.name}</TableCell>
              <TableCell className="font-mono text-xs">{key.key_prefix}</TableCell>
              <TableCell>{key.priority}</TableCell>
              <TableCell>
                <StatusBadge variant={key.is_active ? "active" : "inactive"}>
                  {key.is_active ? "Active" : "Disabled"}
                </StatusBadge>
              </TableCell>
              <TableCell className="flex justify-end gap-1">
                <Button size="icon-sm" variant="ghost" onClick={() => setRotateKey(key)}>
                  <RefreshCw />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  disabled={!providerId || !key.is_active}
                  onClick={() => onDeactivate(key)}
                >
                  <Trash2 />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog
        open={Boolean(rotateKey)}
        onOpenChange={(open) => {
          if (!open) {
            setRotateKey(null);
            setApiKey("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rotate provider key</DialogTitle>
            <DialogDescription>Paste the replacement upstream API key.</DialogDescription>
          </DialogHeader>
          <Input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
          <DialogFooter>
            <Button
              disabled={!rotateKey || !apiKey}
              onClick={() => {
                if (rotateKey) onRotate(rotateKey, apiKey);
                setRotateKey(null);
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

function ResourceModelTable({
  providerId,
  models,
  onAlias,
  onDeactivate,
}: {
  providerId: string;
  models: ProviderModelResponse[];
  onAlias: (model: ProviderModelResponse, alias: string) => void;
  onDeactivate: (model: ProviderModelResponse) => void;
}) {
  const [editModel, setEditModel] = useState<ProviderModelResponse | null>(null);
  const [alias, setAlias] = useState("");

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Provider model</TableHead>
            <TableHead>Alias</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-[1%]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {models.map((model) => (
            <TableRow key={model.id}>
              <TableCell className="font-mono text-xs">{model.provider_model_name}</TableCell>
              <TableCell>{model.alias || "—"}</TableCell>
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
                <Button
                  size="icon-sm"
                  variant="ghost"
                  disabled={!providerId || !model.is_active}
                  onClick={() => onDeactivate(model)}
                >
                  <Trash2 />
                </Button>
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

export function SubscriptionsPanel({
  providers,
  subscriptions,
}: {
  providers: ProviderResponse[];
  subscriptions: SubscriptionResponse[];
}) {
  const queryClient = useQueryClient();
  const form = useForm<SubscriptionValues>({
    resolver: zodResolver(subscriptionSchema),
    defaultValues: { name: "", description: "" },
  });
  const createSubscription = useCreateSubscriptionApiV1SubscriptionsPost({
    mutation: {
      onSuccess: async () => {
        form.reset({ name: "", description: "" });
        await queryClient.invalidateQueries();
      },
    },
  });

  return (
    <section className="mt-6 space-y-4">
      <div>
        <h2 className="text-base font-semibold">Subscriptions</h2>
        <p className="text-sm text-muted-foreground">
          Bundle provider keys, then attach subscriptions to projects.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <form
          className="space-y-4 rounded-lg border p-4"
          onSubmit={form.handleSubmit((values) =>
            createSubscription.mutate({
              data: {
                name: values.name,
                description: values.description || null,
              },
            }),
          )}
        >
          <div className="space-y-1.5">
            <Label htmlFor="subscription-name">Name</Label>
            <Input id="subscription-name" {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="subscription-description">Description</Label>
            <Textarea
              id="subscription-description"
              rows={3}
              {...form.register("description")}
            />
          </div>
          <Button type="submit" disabled={createSubscription.isPending}>
            <Plus />
            {createSubscription.isPending ? "Creating..." : "Create subscription"}
          </Button>
        </form>

        <div className="space-y-3">
          {subscriptions.length === 0 ? (
            <div className="rounded-lg border p-4 text-sm text-muted-foreground">
              No subscriptions yet.
            </div>
          ) : (
            subscriptions.map((subscription) => (
              <SubscriptionRow
                key={subscription.id}
                subscription={subscription}
                providers={providers}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function SubscriptionRow({
  subscription,
  providers,
}: {
  subscription: SubscriptionResponse;
  providers: ProviderResponse[];
}) {
  const queryClient = useQueryClient();
  const form = useForm<SubscriptionProviderKeyValues>({
    resolver: zodResolver(subscriptionProviderKeySchema),
    defaultValues: { provider_id: "", provider_key_id: "", priority: 100 },
  });
  const selectedProviderId = useWatch({ control: form.control, name: "provider_id" });
  const selectedProviderKeyId = useWatch({ control: form.control, name: "provider_key_id" });
  const keysQuery = useListProviderKeysApiV1ProvidersProviderIdKeysGet(selectedProviderId, {
    query: { enabled: Boolean(selectedProviderId) },
  });
  const attachmentsQuery =
    useListSubscriptionProviderKeysApiV1SubscriptionsSubscriptionIdProviderKeysGet(
      subscription.id,
    );
  const attachProviderKey =
    useAttachProviderKeyToSubscriptionApiV1SubscriptionsSubscriptionIdProviderKeysPost({
      mutation: {
        onSuccess: async () => {
          form.reset({ provider_id: "", provider_key_id: "", priority: 100 });
          await queryClient.invalidateQueries();
        },
      },
    });
  const providerKeys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const attachments =
    attachmentsQuery.data?.status === 200 ? attachmentsQuery.data.data : [];
  const activeProviders = providers.filter((provider) => provider.is_active);

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">{subscription.name}</h3>
          {subscription.description ? (
            <p className="text-sm text-muted-foreground">{subscription.description}</p>
          ) : null}
        </div>
        <StatusBadge variant={subscription.is_active ? "active" : "inactive"}>
          {subscription.is_active ? "Active" : "Disabled"}
        </StatusBadge>
      </div>

      <form
        className="grid gap-2 md:grid-cols-[1fr_1fr_90px_auto]"
        onSubmit={form.handleSubmit((values) =>
          attachProviderKey.mutate({
            subscriptionId: subscription.id,
            data: {
              provider_key_id: values.provider_key_id,
              priority: values.priority,
            },
          }),
        )}
      >
        <Select
          value={selectedProviderId}
          onValueChange={(value) => {
            form.setValue("provider_id", value);
            form.setValue("provider_key_id", "");
          }}
        >
          <SelectTrigger>
            <SelectValue placeholder="Provider" />
          </SelectTrigger>
          <SelectContent>
            {activeProviders.map((provider) => (
              <SelectItem key={provider.id} value={provider.id}>
                {provider.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={selectedProviderKeyId}
          onValueChange={(value) => form.setValue("provider_key_id", value)}
          disabled={!selectedProviderId}
        >
          <SelectTrigger>
            <SelectValue placeholder="Provider key" />
          </SelectTrigger>
          <SelectContent>
            {providerKeys
              .filter((key) => key.is_active)
              .map((key) => (
                <SelectItem key={key.id} value={key.id}>
                  {key.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Input
          type="number"
          aria-label="Priority"
          {...form.register("priority", { valueAsNumber: true })}
        />
        <Button type="submit" disabled={attachProviderKey.isPending}>
          <Plus />
          Attach
        </Button>
      </form>

      <SubscriptionProviderKeysTable attachments={attachments} providerKeys={providerKeys} />
      <p className="text-xs text-muted-foreground">
        By default, a subscription exposes all active models for attached provider keys. Model
        narrowing remains available through the API.
      </p>
    </div>
  );
}

function SubscriptionProviderKeysTable({
  attachments,
  providerKeys,
}: {
  attachments: SubscriptionProviderKeyResponse[];
  providerKeys: ProviderKeyResponse[];
}) {
  if (attachments.length === 0) {
    return <p className="text-sm text-muted-foreground">No provider keys attached.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Provider key</TableHead>
          <TableHead>Priority</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {attachments.map((attachment) => {
          const providerKey = providerKeys.find(
            (key) => key.id === attachment.provider_key_id,
          );
          return (
            <TableRow key={attachment.id}>
              <TableCell className="font-medium">
                {providerKey?.name ?? attachment.provider_key_id}
              </TableCell>
              <TableCell>{attachment.priority}</TableCell>
              <TableCell>
                <StatusBadge variant={attachment.is_active ? "active" : "inactive"}>
                  {attachment.is_active ? "Active" : "Disabled"}
                </StatusBadge>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function AddProviderKeyDialog({
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
  const form = useForm<ProviderKeyValues>({
    resolver: zodResolver(providerKeySchema),
    defaultValues: { name: "", api_key: "", priority: 100 },
  });

  useEffect(() => {
    if (entry) {
      form.reset({ name: `${entry.name} key`, api_key: "", priority: 100 });
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

      const keyResponse = await createProviderKeyApiV1ProvidersProviderIdKeysPost(providerId, {
        name: values.name,
        api_key: values.api_key,
        priority: values.priority,
      });
      if (keyResponse.status !== 201) {
        throw new Error("Provider key was not created.");
      }
      await onCreated();
    } catch {
      setIsError(true);
    } finally {
      setIsPending(false);
    }
  });

  return (
    <Dialog open={Boolean(entry)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add provider key</DialogTitle>
          <DialogDescription>
            {entry
              ? `Add an encrypted upstream API key for ${entry.name}.`
              : "Add an encrypted upstream API key."}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-name">Name</Label>
            <Input id="provider-key-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-secret">API key</Label>
            <Input
              id="provider-key-secret"
              type="password"
              autoComplete="off"
              {...form.register("api_key")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-priority">Priority</Label>
            <Input
              id="provider-key-priority"
              type="number"
              {...form.register("priority", { valueAsNumber: true })}
            />
          </div>
          {isError ? <p className="text-sm text-destructive">Provider key was not added.</p> : null}
        </form>
        <DialogFooter>
          <Button disabled={isPending} onClick={submit}>
            {isPending ? "Adding..." : "Add key"}
          </Button>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
      provider_preset: "openai",
      name: "OpenAI",
      slug: "openai",
      base_url: "https://api.openai.com/v1",
      api_key: "",
    },
  });
  const selectedPreset = useWatch({ control: form.control, name: "provider_preset" });

  useEffect(() => {
    if (!open) form.reset();
  }, [open, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button>
          <Plus />
          Add provider
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add provider</SheetTitle>
          <SheetDescription>
            OpenAI-compatible base URL and API key. The key is stored encrypted at rest.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label>Provider type</Label>
            <Select
              value={selectedPreset}
              onValueChange={(value) => {
                const preset = providerPresets.find((item) => item.id === value);
                form.setValue("provider_preset", value);
                if (preset) {
                  form.setValue("name", preset.name);
                  form.setValue("slug", preset.slug);
                  form.setValue("base_url", preset.baseUrl);
                }
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choose provider" />
              </SelectTrigger>
              <SelectContent>
                {providerPresets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    {preset.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-name">Name</Label>
            <Input id="provider-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-slug">Slug</Label>
            <Input id="provider-slug" placeholder="openai" {...form.register("slug")} />
            <p className="text-xs text-muted-foreground">
              Optional provider hint for proxy requests.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-base-url">Base URL</Label>
            <Input
              id="provider-base-url"
              placeholder="https://api.openai.com/v1"
              {...form.register("base_url")}
            />
            {form.formState.errors.base_url ? (
              <p className="text-xs text-destructive">{form.formState.errors.base_url.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-api-key">API key</Label>
            <Input
              id="provider-api-key"
              type="password"
              autoComplete="off"
              {...form.register("api_key")}
            />
            <p className="text-xs text-muted-foreground">
              Optional. You can add provider keys after creating the provider.
            </p>
          </div>
          {isError ? <p className="text-sm text-destructive">Provider was not created.</p> : null}
        </form>
        <SheetFooter>
          <Button type="submit" disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Adding..." : "Add provider"}
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
    defaultValues: { name: "", slug: "", base_url: "", api_key: "" },
  });

  useEffect(() => {
    if (provider) {
      form.reset({
        name: provider.name,
        slug: provider.slug ?? "",
        base_url: provider.base_url,
        api_key: "",
      });
    }
  }, [provider, form]);

  return (
    <Sheet open={Boolean(provider)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit provider</SheetTitle>
          <SheetDescription>Leave the API key blank to keep the existing one.</SheetDescription>
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
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-api-key">New API key</Label>
            <Input
              id="edit-provider-api-key"
              type="password"
              autoComplete="off"
              placeholder="Leave blank to keep current"
              {...form.register("api_key")}
            />
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
