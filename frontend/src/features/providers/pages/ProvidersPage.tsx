import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronDown,
  MoreHorizontal,
  Pencil,
  Plug,
  Plus,
  Power,
  RotateCcw,
  Search,
  Star,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { cn } from "@/lib/utils";
import {
  createProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useCreateProviderApiV1ProvidersPost,
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useGetProviderImpactApiV1ProvidersProviderIdImpactGet,
  useListProvidersApiV1ProvidersGet,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import type { ProviderResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { hasPermission } from "@/features/auth/lib/permissions";

import { EditProviderSheet } from "../components/EditProviderSheet";
import { ProviderLogo } from "../components/ProviderLogo";
import {
  createProviderSchema,
  providerCredentialSchema,
  type CreateProviderValues,
  type ProviderCredentialValues,
} from "../lib/schemas";
import { getProviderReadiness } from "../lib/provider-readiness";

type CatalogSegment = "all" | "configured" | "available" | "custom" | "ready";

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [addKeyTarget, setAddKeyTarget] = useState<ProviderResponse | null>(null);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<CatalogSegment>("all");
  const [disabledOpen, setDisabledOpen] = useState(false);

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const impactQuery = useGetProviderImpactApiV1ProvidersProviderIdImpactGet(
    deactivateTarget?.id ?? "",
    { query: { enabled: Boolean(deactivateTarget) } },
  );
  const deactivateImpact = impactQuery.data?.status === 200 ? impactQuery.data.data : null;
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageProviders = hasPermission(currentUser, "providers.manage");
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const providerStateCounts = providers.reduce(
    (counts, provider) => {
      if (isProviderInitiated(provider)) counts.configured += 1;
      if (provider.is_active && !isProviderInitiated(provider)) counts.available += 1;
      return counts;
    },
    { configured: 0, available: 0 },
  );
  const segmentCounts = {
    all: providers.length,
    configured: providerStateCounts.configured,
    available: providerStateCounts.available,
    custom: providers.filter((provider) => provider.catalog_type === "custom").length,
    ready: providers.filter(isProviderReady).length,
  };
  const catalogEntries = [...providers]
    .filter((entry) => {
      if (segment === "configured") return isProviderInitiated(entry);
      if (segment === "available") return entry.is_active && !isProviderInitiated(entry);
      if (segment === "custom") return entry.catalog_type === "custom";
      if (segment === "ready") return isProviderReady(entry);
      return true;
    })
    .filter((entry) =>
      `${entry.name} ${entry.slug ?? ""} ${entry.base_url}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
    )
    .sort(compareProviders);
  const activeEntries = catalogEntries.filter((entry) => entry.is_active);
  const favoriteEntries = activeEntries.filter((entry) => entry.is_favorite);
  const configuredEntries = activeEntries.filter(
    (entry) => !entry.is_favorite && isProviderInitiated(entry),
  );
  const availableEntries = activeEntries.filter(
    (entry) => !entry.is_favorite && !isProviderInitiated(entry),
  );
  const disabledEntries = catalogEntries.filter((entry) => !entry.is_active);
  const hasProviderFilters = Boolean(search.trim()) || segment !== "all";
  const clearProviderFilters = () => {
    setSearch("");
    setSegment("all");
  };

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
      <div className="space-y-6">
        <PageHeader
          title="Providers"
          description="Default and custom upstream providers for routing, credentials, and model catalogs."
          actions={
            canManageProviders ? (
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
            ) : null
          }
        />

        {providersQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading providers...</p>
        ) : (
          <div className="space-y-4">
            <div className="rounded-md border bg-muted/20 p-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="bg-background pl-9 pr-9"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    aria-label="Search providers"
                    placeholder="Search by provider, slug, or endpoint..."
                  />
                  {search ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="absolute right-1 top-1/2 -translate-y-1/2"
                      onClick={() => setSearch("")}
                      aria-label="Clear provider search"
                    >
                      <X />
                    </Button>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-1 rounded-md border bg-background p-0.5">
                  {(["all", "configured", "available", "custom", "ready"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-label={`${formatSegmentLabel(value)} providers (${segmentCounts[value]})`}
                      aria-pressed={segment === value}
                      onClick={() => setSegment(value)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                        segment === value
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {formatSegmentLabel(value)}
                      <span className="ml-1.5 text-muted-foreground">{segmentCounts[value]}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {catalogEntries.length === 0 ? (
              <EmptyState
                icon={Plug}
                title="No providers match"
                description="Clear filters or try another search."
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    {hasProviderFilters ? (
                      <Button variant="outline" onClick={clearProviderFilters}>
                        Clear filters
                      </Button>
                    ) : null}
                    {canManageProviders ? (
                      <Button onClick={() => setCreateOpen(true)}>Add custom provider</Button>
                    ) : null}
                  </div>
                }
              />
            ) : (
              <div className="space-y-5">
                {favoriteEntries.length > 0 ? (
                  <ProviderGroup
                    title="Favorites"
                    providers={favoriteEntries}
                    onAddKey={setAddKeyTarget}
                    onEdit={setEditTarget}
                    onDeactivate={setDeactivateTarget}
                    onReactivate={(entry) =>
                      updateMutation.mutate({ providerId: entry.id, data: { is_active: true } })
                    }
                    onToggleFavorite={(entry) =>
                      updateMutation.mutate({
                        providerId: entry.id,
                        data: { is_favorite: !entry.is_favorite },
                      })
                    }
                    isUpdating={updateMutation.isPending}
                    canManage={canManageProviders}
                  />
                ) : null}
                <ProviderGroup
                  title={configuredEntries.length > 0 ? "Configured providers" : undefined}
                  providers={configuredEntries}
                  onAddKey={setAddKeyTarget}
                  onEdit={setEditTarget}
                  onDeactivate={setDeactivateTarget}
                  onReactivate={(entry) =>
                    updateMutation.mutate({ providerId: entry.id, data: { is_active: true } })
                  }
                  onToggleFavorite={(entry) =>
                    updateMutation.mutate({
                      providerId: entry.id,
                      data: { is_favorite: !entry.is_favorite },
                    })
                  }
                  isUpdating={updateMutation.isPending}
                  canManage={canManageProviders}
                />
                <ProviderGroup
                  title="Available providers"
                  providers={availableEntries}
                  onAddKey={setAddKeyTarget}
                  onEdit={setEditTarget}
                  onDeactivate={setDeactivateTarget}
                  onReactivate={(entry) =>
                    updateMutation.mutate({ providerId: entry.id, data: { is_active: true } })
                  }
                  onToggleFavorite={(entry) =>
                    updateMutation.mutate({
                      providerId: entry.id,
                      data: { is_favorite: !entry.is_favorite },
                    })
                  }
                  isUpdating={updateMutation.isPending}
                  canManage={canManageProviders}
                />
                {disabledEntries.length > 0 ? (
                  <Collapsible open={disabledOpen} onOpenChange={setDisabledOpen}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        className="w-full justify-between text-muted-foreground"
                      >
                        Disabled providers ({disabledEntries.length})
                        <ChevronDown
                          className={cn("transition-transform", disabledOpen && "rotate-180")}
                        />
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="pt-3">
                      <ProviderGroup
                        providers={disabledEntries}
                        onAddKey={setAddKeyTarget}
                        onEdit={setEditTarget}
                        onDeactivate={setDeactivateTarget}
                        onReactivate={(entry) =>
                          updateMutation.mutate({
                            providerId: entry.id,
                            data: { is_active: true },
                          })
                        }
                        onToggleFavorite={(entry) =>
                          updateMutation.mutate({
                            providerId: entry.id,
                            data: { is_favorite: !entry.is_favorite },
                          })
                        }
                        isUpdating={updateMutation.isPending}
                        canManage={canManageProviders}
                      />
                    </CollapsibleContent>
                  </Collapsible>
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>

      <EditProviderSheet
        provider={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={(data) => {
          if (!editTarget) return;
          updateMutation.mutate({ providerId: editTarget.id, data });
        }}
        isPending={updateMutation.isPending}
      />
      <AddProviderCredentialDialog
        key={addKeyTarget?.id ?? "closed"}
        entry={addKeyTarget}
        onClose={() => setAddKeyTarget(null)}
        onCreated={() => queryClient.invalidateQueries()}
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
          {impactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Checking impact...</p>
          ) : deactivateImpact ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
              <p className="font-medium">Resources affected</p>
              <p className="mt-1 text-muted-foreground">
                {deactivateImpact.access_policies?.length ?? 0} access routes,{" "}
                {deactivateImpact.active_limit_rule_count ?? 0} limit rules,{" "}
                {deactivateImpact.active_pool_count ?? 0} pools, and{" "}
                {deactivateImpact.active_model_count ?? 0} models.
              </p>
              <p className="mt-1 text-muted-foreground">
                Last 30 days: {(deactivateImpact.recent_request_count ?? 0).toLocaleString()}{" "}
                requests.
              </p>
            </div>
          ) : null}
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

function ProviderGroup({
  title,
  providers,
  onAddKey,
  onEdit,
  onDeactivate,
  onReactivate,
  onToggleFavorite,
  isUpdating,
  canManage,
}: {
  title?: string;
  providers: ProviderResponse[];
  onAddKey: (provider: ProviderResponse) => void;
  onEdit: (provider: ProviderResponse) => void;
  onDeactivate: (provider: ProviderResponse) => void;
  onReactivate: (provider: ProviderResponse) => void;
  onToggleFavorite: (provider: ProviderResponse) => void;
  isUpdating: boolean;
  canManage: boolean;
}) {
  if (providers.length === 0) return null;
  return (
    <section className="space-y-2">
      {title ? <h2 className="text-sm font-medium text-muted-foreground">{title}</h2> : null}
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Readiness</TableHead>
              <TableHead className="text-right">Credentials</TableHead>
              <TableHead className="text-right">Models</TableHead>
              <TableHead>Health signal</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {providers.map((entry) => (
              <ProviderCatalogRow
                key={entry.id}
                provider={entry}
                onAddKey={() => onAddKey(entry)}
                onEdit={() => onEdit(entry)}
                onDeactivate={() => onDeactivate(entry)}
                onReactivate={() => onReactivate(entry)}
                onToggleFavorite={() => onToggleFavorite(entry)}
                isUpdating={isUpdating}
                canManage={canManage}
              />
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function ProviderCatalogRow({
  provider,
  onAddKey,
  onEdit,
  onDeactivate,
  onReactivate,
  onToggleFavorite,
  isUpdating,
  canManage,
}: {
  provider: ProviderResponse;
  onAddKey: () => void;
  onEdit: () => void;
  onDeactivate: () => void;
  onReactivate: () => void;
  onToggleFavorite: () => void;
  isUpdating: boolean;
  canManage: boolean;
}) {
  const activeCredentialCount = provider.credential_summary?.active ?? 0;
  const activeModelCount = provider.readiness?.active_model_count ?? 0;
  const readiness = formatProviderReadiness(provider);
  const primaryAction = providerPrimaryAction(provider);

  return (
    <TableRow className={cn("group", !provider.is_active && "bg-muted/20 opacity-70")}>
      <TableCell className="min-w-[260px]">
        <div className="flex items-center gap-3">
          <ProviderLogo iconSlug={provider.slug ?? undefined} name={provider.name} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link className="font-medium hover:underline" to={`/providers/${provider.id}`}>
                {provider.name}
              </Link>
              {provider.catalog_type === "custom" ? (
                <StatusBadge variant="muted">Custom</StatusBadge>
              ) : null}
              {provider.is_favorite ? (
                <Star className="size-3.5 fill-current text-primary" />
              ) : null}
            </div>
            <p className="max-w-md truncate text-xs text-muted-foreground">
              {provider.description ?? "Custom OpenAI-compatible upstream provider."}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <StatusBadge variant={readiness.variant}>{readiness.label}</StatusBadge>
      </TableCell>
      <TableCell className="text-right tabular-nums">{activeCredentialCount}</TableCell>
      <TableCell className="text-right tabular-nums">{activeModelCount}</TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {provider.credential_summary?.valid
          ? provider.operational_state?.circuit_state === "open"
            ? "Circuit open"
            : "Credential valid"
          : "Never"}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          {canManage && primaryAction === "credential" ? (
            <Button size="sm" onClick={onAddKey}>
              <Plus />
              Add credential
            </Button>
          ) : (
            <Button asChild size="sm" variant={primaryAction === "open" ? "outline" : "default"}>
              <Link to={`/providers/${provider.id}`}>
                {primaryAction === "open" ? "Open" : "Complete setup"}
                <ArrowRight />
              </Link>
            </Button>
          )}
          {canManage ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label={`${provider.name} actions`}>
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={onToggleFavorite} disabled={isUpdating}>
                  <Star className={cn("mr-2 size-4", provider.is_favorite && "fill-current")} />
                  {provider.is_favorite ? "Remove favorite" : "Mark as favorite"}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onEdit}>
                  <Pencil className="mr-2 size-4" />
                  Edit provider
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onDeactivate}
                  disabled={!provider.is_active}
                  variant="destructive"
                >
                  <Power className="mr-2 size-4" />
                  Deactivate
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={onReactivate}
                  disabled={provider.is_active || isUpdating}
                >
                  <RotateCcw className="mr-2 size-4" />
                  Reactivate
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  );
}

function formatProviderReadiness(provider: ProviderResponse) {
  const status =
    provider.readiness?.status ?? (provider.is_active ? "needs_credential" : "disabled");
  const states: Record<
    string,
    { label: string; variant: "active" | "inactive" | "error" | "expired" }
  > = {
    ready: { label: "Ready", variant: "active" },
    degraded: { label: "Degraded", variant: "error" },
    disabled: { label: "Disabled", variant: "inactive" },
    needs_credential: { label: "Needs credential", variant: "expired" },
    needs_pool: { label: "Needs pool", variant: "expired" },
    needs_model_sync: { label: "Needs model sync", variant: "expired" },
  };
  return states[status] ?? { label: "Setup incomplete", variant: "expired" as const };
}

function compareProviders(a: ProviderResponse, b: ProviderResponse) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

function isProviderInitiated(provider: ProviderResponse) {
  return (
    provider.catalog_type === "custom" ||
    (provider.credential_summary?.total ?? 0) > 0 ||
    (provider.credential_summary?.active ?? 0) > 0 ||
    (provider.readiness?.active_model_count ?? 0) > 0
  );
}

function isProviderReady(provider: ProviderResponse) {
  return provider.readiness?.status === "ready";
}

function providerPrimaryAction(provider: ProviderResponse) {
  const readiness = getProviderReadiness({
    providerEnabled: provider.is_active,
    credentialCount: provider.credential_summary?.active ?? 0,
    validatedCredentialCount: provider.credential_summary?.valid ?? 0,
    poolCount: provider.readiness?.has_active_pool ? 1 : 0,
    poolsWithCredentialsCount: provider.readiness?.has_active_pool_credential ? 1 : 0,
    modelCount: provider.readiness?.active_model_count ?? 0,
  });
  if (readiness.nextAction === "add_credential" || readiness.nextAction === "test_credentials") {
    return "credential";
  }
  if (readiness.nextAction === "open_playground") return "open";
  return "setup";
}

function formatSegmentLabel(segment: CatalogSegment) {
  if (segment === "all") return "All";
  if (segment === "configured") return "Configured";
  if (segment === "available") return "Available";
  if (segment === "custom") return "Custom";
  return "Ready";
}

function AddProviderCredentialDialog({
  entry,
  onClose,
  onCreated,
}: {
  entry: ProviderResponse | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [isPending, setIsPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const form = useForm<ProviderCredentialValues>({
    resolver: zodResolver(providerCredentialSchema),
    defaultValues: {
      name: entry ? `${entry.name} credential` : "",
      api_key: "",
    },
  });

  const submit = form.handleSubmit(async (values) => {
    if (!entry) return;

    setIsPending(true);
    setErrorMessage(null);
    try {
      const keyResponse = await createProviderCredentialApiV1ProvidersProviderIdCredentialsPost(
        entry.id,
        {
          name: values.name,
          api_key: values.api_key,
        },
      );
      if (keyResponse.status !== 201) {
        throw new Error("Credential could not be created.");
      }
      toast.success(`Credential added to ${entry.name}.`);
      onClose();
      await onCreated();
    } catch (error) {
      if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("Something went wrong. Try again.");
      }
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
        <form className="grid gap-4 overflow-y-auto px-6 py-5" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-name">Name</Label>
            <Input id="provider-key-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="provider-key-secret">API key</Label>
            <Input
              id="provider-key-secret"
              type="password"
              autoComplete="new-password"
              {...form.register("api_key")}
            />
            {form.formState.errors.api_key ? (
              <p className="text-xs text-destructive">{form.formState.errors.api_key.message}</p>
            ) : null}
          </div>
          {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={submit}>
            {isPending ? "Saving..." : "Add credential"}
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
  onSubmit: (values: CreateProviderValues) => void;
  isPending: boolean;
  isError: boolean;
}) {
  const form = useForm<CreateProviderValues>({
    resolver: zodResolver(createProviderSchema),
    defaultValues: {
      name: "",
      slug: "",
      base_url: "",
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        name: "",
        slug: "",
        base_url: "",
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
        <form
          className="grid gap-4 overflow-y-auto px-6 py-5"
          autoComplete="off"
          onSubmit={form.handleSubmit(onSubmit)}
        >
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
