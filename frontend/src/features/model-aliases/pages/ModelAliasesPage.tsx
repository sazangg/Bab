import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import {
  useCreateModelAliasApiV1ModelAliasesPost,
  useDeactivateModelAliasApiV1ModelAliasesAliasIdDelete,
  useListModelAliasesApiV1ModelAliasesGet,
  useUpdateModelAliasApiV1ModelAliasesAliasIdPatch,
} from "@/shared/api/generated/model-aliases/model-aliases";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type { ModelAliasResponse, ProviderResponse } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";

const aliasSchema = z.object({
  alias: z.string().min(1).max(255),
  provider_id: z.string().min(1),
  provider_model: z.string().min(1).max(255),
});

type AliasFormValues = z.infer<typeof aliasSchema>;

export function ModelAliasesPage() {
  const queryClient = useQueryClient();
  const aliasesQuery = useListModelAliasesApiV1ModelAliasesGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const aliases = aliasesQuery.data?.status === 200 ? aliasesQuery.data.data : [];
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const form = useForm<AliasFormValues>({
    resolver: zodResolver(aliasSchema),
    defaultValues: {
      alias: "",
      provider_id: "",
      provider_model: "",
    },
  });
  const createMutation = useCreateModelAliasApiV1ModelAliasesPost({
    mutation: {
      onSuccess: async () => {
        form.reset();
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateMutation = useUpdateModelAliasApiV1ModelAliasesAliasIdPatch({
    mutation: {
      onSuccess: async () => {
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

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-muted-foreground">Routing</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Model aliases</h1>
      </header>

      <section className="rounded-lg border bg-card p-5">
        <div className="mb-5">
          <h2 className="text-base font-semibold">Create alias</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Aliases let clients call Bab with stable internal model names while routing to provider
            models.
          </p>
        </div>
        <form
          className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]"
          onSubmit={form.handleSubmit((values) => createMutation.mutate({ data: values }))}
        >
          <Input label="Alias" placeholder="fast-default" registration={form.register("alias")} />
          <label className="block text-sm font-medium">
            Provider
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              {...form.register("provider_id")}
            >
              <option value="">Select provider</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <Input
            label="Provider model"
            placeholder="gpt-5.4-mini"
            registration={form.register("provider_model")}
          />
          <div className="flex items-end">
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
        {Object.values(form.formState.errors)[0]?.message ? (
          <p className="mt-3 text-sm text-destructive">
            {Object.values(form.formState.errors)[0]?.message}
          </p>
        ) : null}
        {createMutation.isError ? (
          <p className="mt-3 text-sm text-destructive">Model alias was not created.</p>
        ) : null}
      </section>

      <section className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Alias</th>
              <th className="px-3 py-2 font-medium">Provider</th>
              <th className="px-3 py-2 font-medium">Provider model</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {aliases.map((alias) => (
              <AliasRow
                key={alias.id}
                alias={alias}
                providers={providers}
                onToggle={() =>
                  updateMutation.mutate({
                    aliasId: alias.id,
                    data: { is_active: !alias.is_active },
                  })
                }
                onDeactivate={() => {
                  if (window.confirm(`Deactivate alias ${alias.alias}?`)) {
                    deactivateMutation.mutate({ aliasId: alias.id });
                  }
                }}
              />
            ))}
            {aliases.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-muted-foreground" colSpan={5}>
                  No model aliases yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function AliasRow({
  alias,
  providers,
  onToggle,
  onDeactivate,
}: {
  alias: ModelAliasResponse;
  providers: ProviderResponse[];
  onToggle: () => void;
  onDeactivate: () => void;
}) {
  return (
    <tr className="border-t">
      <td className="px-3 py-2 font-medium">{alias.alias}</td>
      <td className="px-3 py-2 text-muted-foreground">
        {providers.find((provider) => provider.id === alias.provider_id)?.name ?? alias.provider_id}
      </td>
      <td className="px-3 py-2">{alias.provider_model}</td>
      <td className="px-3 py-2">{alias.is_active ? "Active" : "Inactive"}</td>
      <td className="flex gap-2 px-3 py-2">
        <Button type="button" variant="outline" onClick={onToggle}>
          {alias.is_active ? "Pause" : "Activate"}
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={!alias.is_active}
          onClick={onDeactivate}
        >
          Deactivate
        </Button>
      </td>
    </tr>
  );
}

function Input({
  label,
  placeholder,
  registration,
}: {
  label: string;
  placeholder?: string;
  registration: UseFormRegisterReturn;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        placeholder={placeholder}
        {...registration}
      />
    </label>
  );
}
