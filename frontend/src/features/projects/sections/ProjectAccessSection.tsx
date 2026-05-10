import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plug, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  useGrantProjectProviderAccessApiV1ProjectsProjectIdProviderAccessPost,
  useRevokeProjectProviderAccessApiV1ProjectsProjectIdProviderAccessProviderIdDelete,
  useUpdateProjectProviderAccessApiV1ProjectsProjectIdProviderAccessProviderIdPatch,
} from "@/shared/api/generated/projects/projects";
import type {
  ProjectProviderAccessResponse,
  ProviderResponse,
} from "@/shared/api/generated/schemas";
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
import { EmptyState } from "@/shared/components/EmptyState";

const grantSchema = z.object({
  provider_id: z.string().min(1, "Pick a provider"),
  allowed_models: z.string().optional(),
});

type GrantValues = z.infer<typeof grantSchema>;

export function ProjectAccessSection({
  projectId,
  providers,
  accessRules,
  isLoading,
}: {
  projectId: string;
  providers: ProviderResponse[];
  accessRules: ProjectProviderAccessResponse[];
  isLoading: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editRule, setEditRule] = useState<ProjectProviderAccessResponse | null>(null);

  const grantedProviderIds = new Set(accessRules.map((rule) => rule.provider_id));
  const availableProviders = providers.filter((p) => !grantedProviderIds.has(p.id) && p.is_active);

  const form = useForm<GrantValues>({
    resolver: zodResolver(grantSchema),
    defaultValues: { provider_id: "", allowed_models: "" },
  });
  const editForm = useForm<Pick<GrantValues, "allowed_models">>({
    defaultValues: { allowed_models: "" },
  });
  const providerId = useWatch({ control: form.control, name: "provider_id" });

  const grantMutation = useGrantProjectProviderAccessApiV1ProjectsProjectIdProviderAccessPost({
    mutation: {
      onSuccess: async () => {
        form.reset();
        setOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const revokeMutation =
    useRevokeProjectProviderAccessApiV1ProjectsProjectIdProviderAccessProviderIdDelete({
      mutation: {
        onSuccess: async () => {
          await queryClient.invalidateQueries();
        },
      },
    });
  const updateMutation =
    useUpdateProjectProviderAccessApiV1ProjectsProjectIdProviderAccessProviderIdPatch({
      mutation: {
        onSuccess: async () => {
          setEditRule(null);
          await queryClient.invalidateQueries();
        },
      },
    });

  useEffect(() => {
    if (editRule) {
      editForm.reset({ allowed_models: editRule.allowed_models?.join(", ") ?? "" });
    }
  }, [editForm, editRule]);

  return (
    <>
      <Card>
        <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Provider access</CardTitle>
            <CardDescription>Which providers and models this project may use.</CardDescription>
          </div>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button size="sm" disabled={availableProviders.length === 0}>
                <Plus />
                Grant access
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Grant provider access</SheetTitle>
                <SheetDescription>
                  Empty model list means all models the provider supports.
                </SheetDescription>
              </SheetHeader>
              <form
                className="grid gap-4 px-4"
                onSubmit={form.handleSubmit((values) =>
                  grantMutation.mutate({
                    projectId,
                    data: {
                      provider_id: values.provider_id,
                      allowed_models: parseModels(values.allowed_models),
                    },
                  }),
                )}
              >
                <div className="space-y-1.5">
                  <Label>Provider</Label>
                  <Select
                    value={providerId}
                    onValueChange={(value) => form.setValue("provider_id", value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select provider" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableProviders.map((provider) => (
                        <SelectItem key={provider.id} value={provider.id}>
                          {provider.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {form.formState.errors.provider_id ? (
                    <p className="text-xs text-destructive">
                      {form.formState.errors.provider_id.message}
                    </p>
                  ) : null}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="grant-models">Allowed models</Label>
                  <Input
                    id="grant-models"
                    placeholder="gpt-4o, gpt-4o-mini"
                    {...form.register("allowed_models")}
                  />
                  <p className="text-xs text-muted-foreground">
                    Comma-separated. Leave blank for all models.
                  </p>
                </div>
              </form>
              <SheetFooter>
                <Button
                  type="submit"
                  disabled={grantMutation.isPending}
                  onClick={form.handleSubmit((values) =>
                    grantMutation.mutate({
                      projectId,
                      data: {
                        provider_id: values.provider_id,
                        allowed_models: parseModels(values.allowed_models),
                      },
                    }),
                  )}
                >
                  {grantMutation.isPending ? "Granting..." : "Grant access"}
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
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading access rules...</p>
        ) : accessRules.length === 0 ? (
          <EmptyState
            icon={Plug}
            title="No provider access yet"
            description="Grant the project access to at least one provider before issuing keys."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Allowed models</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {accessRules.map((rule) => {
                const provider = providers.find((p) => p.id === rule.provider_id);
                return (
                  <TableRow key={rule.id}>
                    <TableCell className="font-medium">
                      {provider?.name ?? rule.provider_id}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {rule.allowed_models?.join(", ") ?? "All models"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Edit access"
                        onClick={() => setEditRule(rule)}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Revoke"
                        disabled={revokeMutation.isPending}
                        onClick={() =>
                          revokeMutation.mutate({
                            projectId,
                            providerId: rule.provider_id,
                          })
                        }
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        </CardContent>
      </Card>

      <Sheet open={Boolean(editRule)} onOpenChange={(isOpen) => !isOpen && setEditRule(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit provider access</SheetTitle>
            <SheetDescription>Leave models blank to allow all provider models.</SheetDescription>
          </SheetHeader>
          <form
            className="grid gap-4 px-4"
            onSubmit={editForm.handleSubmit((values) => {
              if (!editRule) return;
              updateMutation.mutate({
                projectId,
                providerId: editRule.provider_id,
                data: { allowed_models: parseModels(values.allowed_models) },
              });
            })}
          >
            <div className="space-y-1.5">
              <Label>Provider</Label>
              <Input
                value={
                  providers.find((provider) => provider.id === editRule?.provider_id)?.name ??
                  editRule?.provider_id ??
                  ""
                }
                readOnly
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-access-models">Allowed models</Label>
              <Input
                id="edit-access-models"
                placeholder="gpt-4o, gpt-4o-mini"
                {...editForm.register("allowed_models")}
              />
            </div>
          </form>
          <SheetFooter>
            <Button
              type="submit"
              disabled={updateMutation.isPending}
              onClick={editForm.handleSubmit((values) => {
                if (!editRule) return;
                updateMutation.mutate({
                  projectId,
                  providerId: editRule.provider_id,
                  data: { allowed_models: parseModels(values.allowed_models) },
                });
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
    </>
  );
}

function parseModels(value: string | undefined): string[] | null {
  const models = value
    ?.split(",")
    .map((m) => m.trim())
    .filter(Boolean);
  return models && models.length > 0 ? models : null;
}
