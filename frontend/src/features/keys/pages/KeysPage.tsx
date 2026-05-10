import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useQueryState } from "nuqs";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost,
  useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet,
  useListProjectProviderAccessApiV1ProjectsProjectIdProviderAccessGet,
  useListProjectsApiV1ProjectsGet,
  useListVirtualKeysApiV1ProjectsProjectIdKeysGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
  useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type {
  CreatedVirtualKeyResponse,
  ProjectProviderAccessResponse,
  ProviderResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
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
  const [selectedKeyId, setSelectedKeyId] = useQueryState("key");
  const [createdKey, setCreatedKey] = useState<CreatedVirtualKeyResponse | null>(null);
  const [restrictionProviderId, setRestrictionProviderId] = useState("");
  const [restrictionModels, setRestrictionModels] = useState("");
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
  const keyDetailQuery = useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet(
    effectiveProjectId ?? "",
    selectedKeyId ?? "",
    {
      query: { enabled: Boolean(effectiveProjectId && selectedKeyId) },
    },
  );
  const projectAccess = accessQuery.data?.status === 200 ? accessQuery.data.data : [];
  const virtualKeys = keysQuery.data?.status === 200 ? keysQuery.data.data : [];
  const selectedKey =
    (keyDetailQuery.data?.status === 200 ? keyDetailQuery.data.data : null) ??
    virtualKeys.find((key) => key.id === selectedKeyId) ??
    null;
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
        await setSelectedKeyId(null);
        await queryClient.invalidateQueries();
      },
    },
  });
  const updateKeyMutation = useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch({
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
                providers={providers}
                isSelected={key.id === selectedKeyId}
                onSelect={() => {
                  const firstRestriction = key.restrictions?.[0];
                  setRestrictionProviderId(firstRestriction?.provider_id ?? "");
                  setRestrictionModels(firstRestriction?.allowed_models?.join(", ") ?? "");
                  void setSelectedKeyId(key.id);
                }}
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

      <KeyDetailPanel
        virtualKey={selectedKey}
        providers={providers}
        projectAccess={projectAccess}
        restrictionProviderId={restrictionProviderId}
        restrictionModels={restrictionModels}
        onRestrictionProviderChange={setRestrictionProviderId}
        onRestrictionModelsChange={setRestrictionModels}
        onRename={() => {
          if (!effectiveProjectId || !selectedKey) {
            return;
          }
          const name = window.prompt("Virtual key name", selectedKey.name);
          if (name?.trim()) {
            updateKeyMutation.mutate({
              projectId: effectiveProjectId,
              keyId: selectedKey.id,
              data: { name: name.trim() },
            });
          }
        }}
        onUpdateExpiration={() => {
          if (!effectiveProjectId || !selectedKey) {
            return;
          }
          const value = window.prompt(
            "Expiration date/time. Leave blank for no expiration.",
            selectedKey.expires_at ? toDatetimeLocalValue(selectedKey.expires_at) : "",
          );
          if (value !== null) {
            updateKeyMutation.mutate({
              projectId: effectiveProjectId,
              keyId: selectedKey.id,
              data: { expires_at: value ? new Date(value).toISOString() : null },
            });
          }
        }}
        onSaveRestrictions={() => {
          if (!effectiveProjectId || !selectedKey) {
            return;
          }
          updateKeyMutation.mutate({
            projectId: effectiveProjectId,
            keyId: selectedKey.id,
            data: {
              restrictions: restrictionProviderId
                ? [
                    {
                      provider_id: restrictionProviderId,
                      allowed_models: parseModelList(restrictionModels),
                    },
                  ]
                : null,
            },
          });
        }}
        onClose={() => void setSelectedKeyId(null)}
      />
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
  providers,
  isSelected,
  onSelect,
  onRevoke,
}: {
  virtualKey: VirtualKeyResponse;
  providers: ProviderResponse[];
  isSelected: boolean;
  onSelect: () => void;
  onRevoke: () => void;
}) {
  return (
    <tr className="border-t data-[selected=true]:bg-muted/60" data-selected={isSelected}>
      <td className="px-3 py-2 font-medium">{virtualKey.name}</td>
      <td className="px-3 py-2 font-mono text-xs">{virtualKey.key_prefix}</td>
      <td className="px-3 py-2 text-muted-foreground">
        {formatRestrictions(virtualKey, providers)}
      </td>
      <td className="px-3 py-2 text-muted-foreground">
        {virtualKey.expires_at ? new Date(virtualKey.expires_at).toLocaleString() : "Never"}
      </td>
      <td className="px-3 py-2">{virtualKey.revoked_at ? "Revoked" : "Active"}</td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={onSelect}>
            Details
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={Boolean(virtualKey.revoked_at)}
            onClick={onRevoke}
          >
            Revoke
          </Button>
        </div>
      </td>
    </tr>
  );
}

function KeyDetailPanel({
  virtualKey,
  providers,
  projectAccess,
  restrictionProviderId,
  restrictionModels,
  onRestrictionProviderChange,
  onRestrictionModelsChange,
  onRename,
  onUpdateExpiration,
  onSaveRestrictions,
  onClose,
}: {
  virtualKey: VirtualKeyResponse | null;
  providers: ProviderResponse[];
  projectAccess: ProjectProviderAccessResponse[];
  restrictionProviderId: string;
  restrictionModels: string;
  onRestrictionProviderChange: (value: string) => void;
  onRestrictionModelsChange: (value: string) => void;
  onRename: () => void;
  onUpdateExpiration: () => void;
  onSaveRestrictions: () => void;
  onClose: () => void;
}) {
  if (!virtualKey) {
    return null;
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-muted-foreground">Virtual key detail</p>
          <h2 className="mt-1 text-lg font-semibold">{virtualKey.name}</h2>
        </div>
        <Button type="button" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      <dl className="grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-4">
        <DetailItem label="ID" value={virtualKey.id} />
        <DetailItem label="Prefix" value={virtualKey.key_prefix} />
        <DetailItem label="Created" value={new Date(virtualKey.created_at).toLocaleString()} />
        <DetailItem label="Updated" value={new Date(virtualKey.updated_at).toLocaleString()} />
        <DetailItem
          label="Expires"
          value={virtualKey.expires_at ? new Date(virtualKey.expires_at).toLocaleString() : "Never"}
        />
        <DetailItem
          label="Revoked"
          value={virtualKey.revoked_at ? new Date(virtualKey.revoked_at).toLocaleString() : "No"}
        />
        <DetailItem label="Restrictions" value={formatRestrictions(virtualKey, providers)} />
      </dl>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onRename}>
          Rename
        </Button>
        <Button type="button" variant="outline" onClick={onUpdateExpiration}>
          Expiration
        </Button>
      </div>

      <div className="mt-5 grid gap-3 rounded-md border bg-muted/30 p-3 md:grid-cols-[1fr_1fr_auto]">
        <label className="block text-sm font-medium">
          Narrow to provider
          <select
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            value={restrictionProviderId}
            onChange={(event) => onRestrictionProviderChange(event.target.value)}
          >
            <option value="">Project inherited access</option>
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
          placeholder="gpt-5.4-mini, gpt-5.4"
          value={restrictionModels}
          onChange={(event) => onRestrictionModelsChange(event.target.value)}
        />
        <div className="flex items-end">
          <Button type="button" onClick={onSaveRestrictions}>
            Save restrictions
          </Button>
        </div>
      </div>
    </section>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border bg-muted/30 px-3 py-2">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate font-medium">{value}</dd>
    </div>
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

function formatRestrictions(virtualKey: VirtualKeyResponse, providers: ProviderResponse[]) {
  return (
    virtualKey.restrictions
      ?.map((restriction) => {
        const provider =
          providers.find((item) => item.id === restriction.provider_id)?.name ??
          restriction.provider_id;
        return `${provider}: ${restriction.allowed_models?.join(", ") ?? "all models"}`;
      })
      .join(" | ") ?? "Project inherited access"
  );
}

function toDatetimeLocalValue(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 16);
}
