import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plug, Plus, Power, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  useCreateProviderApiV1ProvidersPost,
  useDeactivateProviderApiV1ProvidersProviderIdDelete,
  useListProvidersApiV1ProvidersGet,
  useUpdateProviderApiV1ProvidersProviderIdPatch,
} from "@/shared/api/generated/providers/providers";
import type { ProviderResponse } from "@/shared/api/generated/schemas";
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
  base_url: z.url(),
  api_key: z.string().min(1),
});

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(1).max(255),
  base_url: z.url(),
  api_key: z.string().optional(),
});

type EditValues = z.infer<typeof editSchema>;

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<ProviderResponse | null>(null);

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];

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
        description="LLM provider credentials. Stored encrypted; secrets are write-only."
        actions={
          <CreateProviderSheet
            open={createOpen}
            onOpenChange={setCreateOpen}
            onSubmit={(values) =>
              createMutation.mutate({
                data: { ...values, adapter_type: "openai_compat" },
              })
            }
            isPending={createMutation.isPending}
            isError={createMutation.isError}
          />
        }
      />

      {providersQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading providers...</p>
      ) : providers.length === 0 ? (
        <EmptyState
          icon={Plug}
          title="No providers yet"
          description="Add your first OpenAI-compatible provider credential."
          action={<Button onClick={() => setCreateOpen(true)}>Add provider</Button>}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Base URL</TableHead>
                <TableHead>Adapter</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.map((provider) => (
                <TableRow key={provider.id}>
                  <TableCell className="font-medium">{provider.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {provider.base_url}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{provider.adapter_type}</TableCell>
                  <TableCell>
                    <StatusBadge variant={provider.is_active ? "active" : "inactive"}>
                      {provider.is_active ? "Active" : "Disabled"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label="Provider actions">
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => setEditTarget(provider)}>
                          <Pencil className="mr-2 size-4" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => setEditTarget(provider)}>
                          <RefreshCw className="mr-2 size-4" />
                          Rotate API key
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onSelect={() => setDeactivateTarget(provider)}
                          disabled={!provider.is_active}
                          variant="destructive"
                        >
                          <Power className="mr-2 size-4" />
                          Deactivate
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onSelect={() =>
                            updateMutation.mutate({
                              providerId: provider.id,
                              data: { is_active: true },
                            })
                          }
                          disabled={provider.is_active || updateMutation.isPending}
                        >
                          <RotateCcw className="mr-2 size-4" />
                          Reactivate
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
              base_url: values.base_url,
              ...(values.api_key ? { api_key: values.api_key } : {}),
            },
          });
        }}
        isPending={updateMutation.isPending}
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
    defaultValues: { name: "", base_url: "", api_key: "" },
  });

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
            <Label htmlFor="provider-name">Name</Label>
            <Input id="provider-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
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
    defaultValues: { name: "", base_url: "", api_key: "" },
  });

  useEffect(() => {
    if (provider) {
      form.reset({ name: provider.name, base_url: provider.base_url, api_key: "" });
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
