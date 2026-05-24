import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plug, Plus, Power, RotateCcw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
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

import { EditProviderSheet } from "../components/EditProviderSheet";
import { ProviderLogo } from "../components/ProviderLogo";
import {
  createProviderSchema,
  providerCredentialSchema,
  type CreateProviderValues,
  type ProviderCredentialValues,
} from "../lib/schemas";

type CatalogSegment = "all" | "default" | "custom" | "ready";

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [addKeyTarget, setAddKeyTarget] = useState<ProviderResponse | null>(null);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);
  const [search, setSearch] = useState("");
  const [segment, setSegment] = useState<CatalogSegment>("all");

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const segmentCounts = {
    all: providers.length,
    default: providers.filter((provider) => provider.catalog_type === "default").length,
    custom: providers.filter((provider) => provider.catalog_type === "custom").length,
    ready: providers.filter((provider) => provider.readiness?.is_ready).length,
  };
  const catalogEntries = providers
    .filter((entry) => {
      if (segment === "default") return entry.catalog_type === "default";
      if (segment === "custom") return entry.catalog_type === "custom";
      if (segment === "ready") return Boolean(entry.readiness?.is_ready);
      return true;
    })
    .filter((entry) =>
      `${entry.name} ${entry.slug ?? ""} ${entry.base_url}`
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
        description="Default and custom OpenAI-compatible upstream providers."
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
              {(["all", "default", "custom", "ready"] as const).map((value) => (
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
                  key={entry.id}
                  provider={entry}
                  onAddKey={() => setAddKeyTarget(entry)}
                  onEdit={() => setEditTarget(entry)}
                  onDeactivate={() => setDeactivateTarget(entry)}
                  onReactivate={() =>
                    updateMutation.mutate({
                      providerId: entry.id,
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
        key={addKeyTarget?.id ?? "closed"}
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
  provider,
  onAddKey,
  onEdit,
  onDeactivate,
  onReactivate,
  isUpdating,
}: {
  provider: ProviderResponse;
  onAddKey: () => void;
  onEdit: () => void;
  onDeactivate: () => void;
  onReactivate: () => void;
  isUpdating: boolean;
}) {
  const activeCredentialCount = provider.credential_summary?.active ?? 0;
  const needsAttention = provider.is_active && !provider.readiness?.is_ready;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors hover:bg-muted/30",
        !provider.is_active && "opacity-60",
      )}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <Link className="min-w-0 flex-1 space-y-2" to={`/providers/${provider.id}`}>
          <div className="flex items-center gap-3">
            <ProviderLogo iconSlug={provider.slug ?? undefined} name={provider.name} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-medium">{provider.name}</h2>
                <StatusBadge variant={provider.catalog_type === "default" ? "active" : "muted"}>
                  {provider.catalog_type === "default" ? "Default" : "Custom"}
                </StatusBadge>
                <StatusBadge variant={provider.is_active ? "active" : "inactive"}>
                  {provider.is_active ? "Enabled" : "Disabled"}
                </StatusBadge>
                {provider.readiness?.is_ready ? (
                  <StatusBadge variant="active">Ready</StatusBadge>
                ) : null}
                {needsAttention ? (
                  <StatusBadge variant="expired">Setup incomplete</StatusBadge>
                ) : null}
                {activeCredentialCount > 0 ? (
                  <span className="text-xs text-muted-foreground">
                    {activeCredentialCount} active{" "}
                    {activeCredentialCount === 1 ? "credential" : "credentials"}
                  </span>
                ) : null}
              </div>
              <p className="text-sm text-muted-foreground">
                {provider.description ?? "Custom OpenAI-compatible upstream provider."}
              </p>
            </div>
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground">{provider.base_url}</p>
        </Link>

        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" onClick={onAddKey}>
            <Plus />
            Add credential
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link to={`/providers/${provider.id}`}>Open</Link>
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
                disabled={!provider.is_active}
                variant="destructive"
              >
                <Power className="mr-2 size-4" />
                Deactivate
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onReactivate} disabled={provider.is_active || isUpdating}>
                <RotateCcw className="mr-2 size-4" />
                Reactivate
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
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
