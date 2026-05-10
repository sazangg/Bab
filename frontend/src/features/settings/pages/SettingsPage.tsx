import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  useCreateModelAliasApiV1ModelAliasesPost,
  useDeactivateModelAliasApiV1ModelAliasesAliasIdDelete,
  useListModelAliasesApiV1ModelAliasesGet,
  useUpdateModelAliasApiV1ModelAliasesAliasIdPatch,
} from "@/shared/api/generated/model-aliases/model-aliases";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type { ModelAliasResponse } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

const aliasSchema = z.object({
  alias: z.string().min(1).max(255),
  provider_id: z.string().min(1),
  provider_model: z.string().min(1).max(255),
});

type AliasValues = z.infer<typeof aliasSchema>;

export function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Workspace-level configuration." />
      <Tabs defaultValue="aliases" className="space-y-4">
        <TabsList>
          <TabsTrigger value="aliases">Model aliases</TabsTrigger>
        </TabsList>
        <TabsContent value="aliases">
          <ModelAliasesCard />
        </TabsContent>
      </Tabs>
    </>
  );
}

function ModelAliasesCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editAlias, setEditAlias] = useState<ModelAliasResponse | null>(null);
  const aliasesQuery = useListModelAliasesApiV1ModelAliasesGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const aliases = aliasesQuery.data?.status === 200 ? aliasesQuery.data.data : [];
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];

  const form = useForm<AliasValues>({
    resolver: zodResolver(aliasSchema),
    defaultValues: { alias: "", provider_id: "", provider_model: "" },
  });
  const editForm = useForm<AliasValues>({
    resolver: zodResolver(aliasSchema),
    defaultValues: { alias: "", provider_id: "", provider_model: "" },
  });
  const aliasProviderId = useWatch({ control: form.control, name: "provider_id" });
  const editProviderId = useWatch({ control: editForm.control, name: "provider_id" });

  const createMutation = useCreateModelAliasApiV1ModelAliasesPost({
    mutation: {
      onSuccess: async () => {
        form.reset();
        setOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const deactivateMutation = useDeactivateModelAliasApiV1ModelAliasesAliasIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateMutation = useUpdateModelAliasApiV1ModelAliasesAliasIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditAlias(null);
        await queryClient.invalidateQueries();
      },
    },
  });

  useEffect(() => {
    if (editAlias) {
      editForm.reset({
        alias: editAlias.alias,
        provider_id: editAlias.provider_id,
        provider_model: editAlias.provider_model,
      });
    }
  }, [editAlias, editForm]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Model aliases</CardTitle>
            <CardDescription>
              Stable names that map to provider model names. Optional.
            </CardDescription>
          </div>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button size="sm" disabled={providers.length === 0}>
                <Plus />
                New alias
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>New model alias</SheetTitle>
                <SheetDescription>
                  Clients can send the alias name. Bab routes to the underlying provider model.
                </SheetDescription>
              </SheetHeader>
              <form
                className="grid gap-4 px-4"
                onSubmit={form.handleSubmit((values) => createMutation.mutate({ data: values }))}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="alias-name">Alias</Label>
                  <Input id="alias-name" placeholder="bab-fast" {...form.register("alias")} />
                </div>
                <div className="space-y-1.5">
                  <Label>Provider</Label>
                  <Select
                    value={aliasProviderId}
                    onValueChange={(value) => form.setValue("provider_id", value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select provider" />
                    </SelectTrigger>
                    <SelectContent>
                      {providers.map((provider) => (
                        <SelectItem key={provider.id} value={provider.id}>
                          {provider.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="alias-model">Provider model</Label>
                  <Input
                    id="alias-model"
                    placeholder="gpt-4o-mini"
                    {...form.register("provider_model")}
                  />
                </div>
              </form>
              <SheetFooter>
                <Button
                  type="submit"
                  disabled={createMutation.isPending}
                  onClick={form.handleSubmit((values) => createMutation.mutate({ data: values }))}
                >
                  {createMutation.isPending ? "Saving..." : "Create alias"}
                </Button>
                <SheetClose asChild>
                  <Button variant="outline">Cancel</Button>
                </SheetClose>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </div>
      </CardHeader>
      <CardContent>
        {aliasesQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Loading aliases...</p>
        ) : aliases.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="No aliases yet"
            description="Aliases let clients use stable names like 'bab-fast' that map to a provider model."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Alias</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Provider model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {aliases.map((alias) => (
                <TableRow key={alias.id}>
                  <TableCell className="font-mono text-xs">{alias.alias}</TableCell>
                  <TableCell>
                    {providers.find((p) => p.id === alias.provider_id)?.name ?? alias.provider_id}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{alias.provider_model}</TableCell>
                  <TableCell>
                    <StatusBadge variant={alias.is_active ? "active" : "inactive"}>
                      {alias.is_active ? "Active" : "Inactive"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Edit alias"
                      onClick={() => setEditAlias(alias)}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Reactivate alias"
                      disabled={alias.is_active || updateMutation.isPending}
                      onClick={() =>
                        updateMutation.mutate({
                          aliasId: alias.id,
                          data: { is_active: true },
                        })
                      }
                    >
                      <RotateCcw />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Deactivate alias"
                      disabled={!alias.is_active || deactivateMutation.isPending}
                      onClick={() => deactivateMutation.mutate({ aliasId: alias.id })}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Sheet open={Boolean(editAlias)} onOpenChange={(isOpen) => !isOpen && setEditAlias(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit model alias</SheetTitle>
            <SheetDescription>Change the stable alias or its provider target.</SheetDescription>
          </SheetHeader>
          <form
            className="grid gap-4 px-4"
            onSubmit={editForm.handleSubmit((values) => {
              if (!editAlias) return;
              updateMutation.mutate({ aliasId: editAlias.id, data: values });
            })}
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-alias-name">Alias</Label>
              <Input id="edit-alias-name" {...editForm.register("alias")} />
            </div>
            <div className="space-y-1.5">
              <Label>Provider</Label>
              <Select
                value={editProviderId}
                onValueChange={(value) => editForm.setValue("provider_id", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select provider" />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((provider) => (
                    <SelectItem key={provider.id} value={provider.id}>
                      {provider.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-alias-model">Provider model</Label>
              <Input id="edit-alias-model" {...editForm.register("provider_model")} />
            </div>
          </form>
          <SheetFooter>
            <Button
              type="submit"
              disabled={updateMutation.isPending}
              onClick={editForm.handleSubmit((values) => {
                if (!editAlias) return;
                updateMutation.mutate({ aliasId: editAlias.id, data: values });
              })}
            >
              {updateMutation.isPending ? "Saving..." : "Save changes"}
            </Button>
            <SheetClose asChild>
              <Button variant="outline">Cancel</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </Card>
  );
}
