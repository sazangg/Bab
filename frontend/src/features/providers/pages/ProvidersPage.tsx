import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plug, Plus, Power, RotateCcw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";

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
import { cn } from "@/lib/utils";
import {
  createProviderApiV1ProvidersPost,
  createProviderCredentialApiV1ProvidersProviderIdCredentialsPost,
  useCreateProviderApiV1ProvidersPost,
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useListProvidersApiV1ProvidersGet,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import type { ProviderResponse } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { EditProviderSheet, RoutingPolicyField } from "../components/EditProviderSheet";
import { ProviderLogo } from "../components/ProviderLogo";
import { formatRoutingPolicy } from "../lib/format";
import { providerPresets, type ProviderCatalogEntry } from "../lib/presets";
import {
  createProviderSchema,
  providerCredentialSchema,
  type CreateProviderValues,
  type ProviderCredentialValues,
} from "../lib/schemas";

type CatalogSegment = "all" | "configured" | "custom";

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [addKeyTarget, setAddKeyTarget] = useState<ProviderCatalogEntry | null>(null);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<CatalogSegment>("all");

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
      simpleIcon: preset.simpleIcon,
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
  const allEntries = [...customEntries, ...knownEntries].sort(
    (a, b) => Number(Boolean(b.provider)) - Number(Boolean(a.provider)),
  );
  const segmentCounts = {
    all: allEntries.length,
    configured: allEntries.filter((entry) => entry.provider).length,
    custom: allEntries.filter((entry) => entry.isCustom).length,
  };
  const catalogEntries = allEntries
    .filter((entry) => {
      if (segment === "configured") return Boolean(entry.provider);
      if (segment === "custom") return entry.isCustom;
      return true;
    })
    .filter((entry) =>
      `${entry.name} ${entry.slug ?? ""} ${entry.baseUrl}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
    );

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
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="relative max-w-md flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search providers..."
              />
            </div>
            <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
              {(["all", "configured", "custom"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSegment(value)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                    segment === value
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {value}
                  <span className="ml-1.5 text-muted-foreground">{segmentCounts[value]}</span>
                </button>
              ))}
            </div>
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
        onSubmit={(data) => {
          if (!editTarget) return;
          updateMutation.mutate({ providerId: editTarget.id, data });
        }}
        isPending={updateMutation.isPending}
      />
      <AddProviderCredentialDialog
        key={addKeyTarget?.key ?? "closed"}
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
  const activeCredentialCount = entry.provider?.credential_summary?.active ?? 0;
  const needsAttention = entry.provider && entry.provider.is_active && activeCredentialCount === 0;

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
            <ProviderLogo iconSlug={entry.simpleIcon} name={entry.name} />
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
                {needsAttention ? (
                  <StatusBadge variant="expired">Needs credential</StatusBadge>
                ) : null}
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
            {entry.provider ? "Add credential" : "Set up"}
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

class ProviderStepError extends Error {
  step: "provider" | "credential";
  constructor(step: "provider" | "credential", message: string) {
    super(message);
    this.step = step;
  }
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
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const form = useForm<ProviderCredentialValues>({
    resolver: zodResolver(providerCredentialSchema),
    defaultValues: {
      name: entry ? `${entry.name} credential` : "",
      api_key: "",
      priority: 100,
    },
  });
  const isNewProvider = Boolean(entry && !entry.provider);

  const submit = form.handleSubmit(async (values) => {
    if (!entry) return;

    setIsPending(true);
    setErrorMessage(null);
    let providerCreatedHere = false;
    try {
      let providerId = entry.provider?.id;
      if (!providerId) {
        const response = await createProviderApiV1ProvidersPost({
          name: entry.name,
          ...(entry.slug ? { slug: entry.slug } : {}),
          base_url: entry.baseUrl,
        });
        if (response.status !== 201) {
          throw new ProviderStepError("provider", "Provider could not be created.");
        }
        providerId = response.data.id;
        providerCreatedHere = true;
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
        throw new ProviderStepError("credential", "Credential could not be created.");
      }
      toast.success(
        providerCreatedHere
          ? `${entry.name} is set up with an initial credential.`
          : `Credential added to ${entry.name}.`,
      );
      await onCreated();
    } catch (error) {
      if (
        error instanceof ProviderStepError &&
        error.step === "credential" &&
        providerCreatedHere
      ) {
        setErrorMessage(
          `${entry.name} was created, but the credential failed. The provider is now visible in the catalog — try adding the credential again.`,
        );
      } else if (error instanceof ProviderStepError) {
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
          <SheetTitle>{isNewProvider ? `Set up ${entry?.name}` : "Add credential"}</SheetTitle>
          <SheetDescription>
            {isNewProvider
              ? `We'll register ${entry?.name} as a provider, then add this first credential.`
              : entry
                ? `Add an encrypted upstream API key for ${entry.name}.`
                : "Add an encrypted upstream API key."}
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 px-4" onSubmit={submit}>
          {isNewProvider && entry ? (
            <div className="rounded-md border bg-muted/30 p-3 text-xs">
              <p className="font-medium text-foreground">Step 1 · Provider</p>
              <dl className="mt-1.5 space-y-0.5 text-muted-foreground">
                <div className="flex justify-between gap-2">
                  <dt>Name</dt>
                  <dd className="font-medium text-foreground">{entry.name}</dd>
                </div>
                {entry.slug ? (
                  <div className="flex justify-between gap-2">
                    <dt>Slug</dt>
                    <dd className="font-mono text-foreground">{entry.slug}</dd>
                  </div>
                ) : null}
                <div className="flex justify-between gap-2">
                  <dt>Base URL</dt>
                  <dd className="truncate font-mono text-foreground">{entry.baseUrl}</dd>
                </div>
              </dl>
              <p className="mt-2 text-muted-foreground">
                You can edit any of these later from Settings on the provider page.
              </p>
            </div>
          ) : null}
          {isNewProvider ? (
            <p className="-mb-1 text-xs font-medium">Step 2 · First credential</p>
          ) : null}
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
          {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={submit}>
            {isPending
              ? "Saving..."
              : isNewProvider
                ? "Set up and add credential"
                : "Add credential"}
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
