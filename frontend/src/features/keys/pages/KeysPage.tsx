import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useQueryState } from "nuqs";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost,
  useListProjectProviderAccessApiV1ProjectsProjectIdProviderAccessGet,
  useListProjectsApiV1ProjectsGet,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
} from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type { CreatedVirtualKeyResponse, VirtualKeyResponse } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";

const keySchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
  provider_id: z.string().optional(),
  allowed_models: z.string().optional(),
});

type KeyFormValues = z.infer<typeof keySchema>;

export function KeysPage() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useQueryState("project");
  const [createdKey, setCreatedKey] = useState<CreatedVirtualKeyResponse | null>(null);
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const projects = useMemo(
    () => (projectsQuery.data?.status === 200 ? projectsQuery.data.data : []),
    [projectsQuery.data],
  );
  const providers = useMemo(
    () => (providersQuery.data?.status === 200 ? providersQuery.data.data : []),
    [providersQuery.data],
  );
  const selectedProject =
    projects.find((project) => project.id === selectedProjectId) ?? projects[0];
  const effectiveProjectId = selectedProject?.id;
  const accessQuery = useListProjectProviderAccessApiV1ProjectsProjectIdProviderAccessGet(
    effectiveProjectId ?? "",
    { query: { enabled: Boolean(effectiveProjectId) } },
  );
  const keysQuery = useListVirtualKeysApiV1ProjectsProjectIdKeysGet(effectiveProjectId ?? "", {
    query: { enabled: Boolean(effectiveProjectId) },
  });
  const projectAccess = accessQuery.data?.status === 200 ? accessQuery.data.data : [];
  const virtualKeys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const form = useForm<KeyFormValues>({
    resolver: zodResolver(keySchema),
    defaultValues: {
      name: "",
      expires_at: "",
      provider_id: "",
      allowed_models: "",
    },
  });
  const createKeyMutation = useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          setCreatedKey(response.data);
          form.reset();
          await queryClient.invalidateQueries();
        }
      },
    },
  });
  const revokeKeyMutation = useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
      },
    },
  });

  useEffect(() => {
    if (!selectedProjectId && projects[0]?.id) {
      void setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId, setSelectedProjectId]);

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-muted-foreground">Access control</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Virtual keys</h1>
      </header>

      <section className="rounded-lg border bg-card p-5">
        <div className="mb-5 grid gap-3 md:grid-cols-[1fr_2fr]">
          <label className="block text-sm font-medium">
            Project
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              value={effectiveProjectId ?? ""}
              onChange={(event) => void setSelectedProjectId(event.target.value)}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
            <p className="font-medium">Inherited project access</p>
            <p className="mt-1 text-muted-foreground">
              {projectAccess.length === 0
                ? "No providers attached to this project yet."
                : projectAccess
                    .map((access) => {
                      const provider = providers.find((item) => item.id === access.provider_id);
                      return `${provider?.name ?? access.provider_id}: ${
                        access.allowed_models?.join(", ") ?? "all models"
                      }`;
                    })
                    .join(" | ")}
            </p>
          </div>
        </div>

        <form
          className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr_1fr_auto]"
          onSubmit={form.handleSubmit((values) => {
            if (!effectiveProjectId) {
              return;
            }
            createKeyMutation.mutate({
              projectId: effectiveProjectId,
              data: {
                name: values.name,
                expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
                restrictions: values.provider_id
                  ? [
                      {
                        provider_id: values.provider_id,
                        allowed_models: parseModelList(values.allowed_models),
                      },
                    ]
                  : null,
              },
            });
          })}
        >
          <Input label="Name" {...form.register("name")} />
          <Input label="Expires at" type="datetime-local" {...form.register("expires_at")} />
          <label className="block text-sm font-medium">
            Narrow to provider
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              {...form.register("provider_id")}
            >
              <option value="">No key restriction</option>
              {projectAccess.map((access) => {
                const provider = providers.find((item) => item.id === access.provider_id);
                return (
                  <option key={access.provider_id} value={access.provider_id}>
                    {provider?.name ?? access.provider_id}
                  </option>
                );
              })}
            </select>
          </label>
          <Input
            label="Allowed models"
            placeholder="gpt-5.4-mini"
            {...form.register("allowed_models")}
          />
          <div className="flex items-end">
            <Button type="submit" disabled={!effectiveProjectId || createKeyMutation.isPending}>
              {createKeyMutation.isPending ? "Creating..." : "Create key"}
            </Button>
          </div>
        </form>
        {createdKey ? (
          <CreatedKeyNotice createdKey={createdKey} onDismiss={() => setCreatedKey(null)} />
        ) : null}
      </section>

      <section className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Prefix</th>
              <th className="px-3 py-2 font-medium">Restrictions</th>
              <th className="px-3 py-2 font-medium">Expiration</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {virtualKeys.map((key) => (
              <KeyRow
                key={key.id}
                virtualKey={key}
                onRevoke={() => {
                  if (effectiveProjectId && window.confirm(`Revoke ${key.name}?`)) {
                    revokeKeyMutation.mutate({ projectId: effectiveProjectId, keyId: key.id });
                  }
                }}
              />
            ))}
            {virtualKeys.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-muted-foreground">
                  No virtual keys for this project.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function CreatedKeyNotice({
  createdKey,
  onDismiss,
}: {
  createdKey: CreatedVirtualKeyResponse;
  onDismiss: () => void;
}) {
  return (
    <div className="mt-4 rounded-md border border-primary/30 bg-accent p-3 text-sm">
      <p className="font-medium">Raw key shown once</p>
      <div className="mt-2 flex gap-2">
        <code className="min-w-0 flex-1 overflow-auto rounded border bg-background px-2 py-1">
          {createdKey.key}
        </code>
        <Button
          type="button"
          variant="outline"
          onClick={() => void navigator.clipboard.writeText(createdKey.key)}
        >
          Copy
        </Button>
        <Button type="button" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function KeyRow({
  virtualKey,
  onRevoke,
}: {
  virtualKey: VirtualKeyResponse;
  onRevoke: () => void;
}) {
  return (
    <tr className="border-t">
      <td className="px-3 py-2 font-medium">{virtualKey.name}</td>
      <td className="px-3 py-2 font-mono text-xs">{virtualKey.key_prefix}</td>
      <td className="px-3 py-2 text-muted-foreground">
        {virtualKey.restrictions
          ?.map(
            (restriction) =>
              `${restriction.provider_id}: ${restriction.allowed_models?.join(", ") ?? "all"}`,
          )
          .join(" | ") ?? "Project inherited access"}
      </td>
      <td className="px-3 py-2 text-muted-foreground">
        {virtualKey.expires_at ? new Date(virtualKey.expires_at).toLocaleString() : "Never"}
      </td>
      <td className="px-3 py-2">{virtualKey.revoked_at ? "Revoked" : "Active"}</td>
      <td className="px-3 py-2">
        <Button
          type="button"
          variant="destructive"
          disabled={Boolean(virtualKey.revoked_at)}
          onClick={onRevoke}
        >
          Revoke
        </Button>
      </td>
    </tr>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const { label, ...inputProps } = props;
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        {...inputProps}
      />
    </label>
  );
}

function parseModelList(value: string | undefined) {
  const models = value
    ?.split(",")
    .map((model) => model.trim())
    .filter(Boolean);
  return models && models.length > 0 ? models : null;
}
