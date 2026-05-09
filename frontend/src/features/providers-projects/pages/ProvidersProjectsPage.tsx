import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useQueryState } from "nuqs";
import type { ReactNode } from "react";
import { useEffect, useMemo } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import {
  useCreateProjectApiV1ProjectsPost,
  useGrantProjectProviderAccessApiV1ProjectsProjectIdProviderAccessPost,
  useListProjectProviderAccessApiV1ProjectsProjectIdProviderAccessGet,
  useListProjectsApiV1ProjectsGet,
} from "@/shared/api/generated/projects/projects";
import {
  useCreateProviderApiV1ProvidersPost,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";
import type {
  ProjectProviderAccessResponse,
  ProviderResponse,
} from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";

const providerSchema = z.object({
  name: z.string().min(1).max(255),
  base_url: z.url(),
  api_key: z.string().min(1),
});

const projectSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(1000).optional(),
});

const accessSchema = z.object({
  provider_id: z.string().min(1),
  allowed_models: z.string().optional(),
});

type ProviderFormValues = z.infer<typeof providerSchema>;
type ProjectFormValues = z.infer<typeof projectSchema>;
type AccessFormValues = z.infer<typeof accessSchema>;

export function ProvidersProjectsPage() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useQueryState("project");
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const providers = useMemo(
    () => (providersQuery.data?.status === 200 ? providersQuery.data.data : []),
    [providersQuery.data],
  );
  const projects = useMemo(
    () => (projectsQuery.data?.status === 200 ? projectsQuery.data.data : []),
    [projectsQuery.data],
  );
  const selectedProject =
    projects.find((project) => project.id === selectedProjectId) ?? projects[0];
  const effectiveProjectId = selectedProject?.id;
  const accessQuery = useListProjectProviderAccessApiV1ProjectsProjectIdProviderAccessGet(
    effectiveProjectId ?? "",
    {
      query: {
        enabled: Boolean(effectiveProjectId),
      },
    },
  );
  const providerForm = useForm<ProviderFormValues>({
    resolver: zodResolver(providerSchema),
    defaultValues: {
      name: "",
      base_url: "",
      api_key: "",
    },
  });
  const projectForm = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      name: "",
      description: "",
    },
  });
  const accessForm = useForm<AccessFormValues>({
    resolver: zodResolver(accessSchema),
    defaultValues: {
      provider_id: "",
      allowed_models: "",
    },
  });
  const createProviderMutation = useCreateProviderApiV1ProvidersPost({
    mutation: {
      onSuccess: async () => {
        providerForm.reset();
        await queryClient.invalidateQueries();
      },
    },
  });
  const createProjectMutation = useCreateProjectApiV1ProjectsPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          projectForm.reset();
          await setSelectedProjectId(response.data.id);
          await queryClient.invalidateQueries();
        }
      },
    },
  });
  const grantAccessMutation = useGrantProjectProviderAccessApiV1ProjectsProjectIdProviderAccessPost(
    {
      mutation: {
        onSuccess: async () => {
          accessForm.reset();
          await queryClient.invalidateQueries();
        },
      },
    },
  );

  useEffect(() => {
    if (!selectedProjectId && projects[0]?.id) {
      void setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId, setSelectedProjectId]);

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-muted-foreground">Control plane</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Providers & projects</h1>
      </header>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="Providers" description="Credentials are write-only after creation.">
          <form
            className="grid gap-3"
            onSubmit={providerForm.handleSubmit((values) =>
              createProviderMutation.mutate({
                data: {
                  ...values,
                  adapter_type: "openai_compat",
                },
              }),
            )}
          >
            <TextInput label="Name" registration={providerForm.register("name")} />
            <TextInput
              label="Base URL"
              placeholder="https://api.openai.com/v1"
              registration={providerForm.register("base_url")}
            />
            <TextInput
              label="API key"
              type="password"
              registration={providerForm.register("api_key")}
            />
            <FormError message={firstError(providerForm.formState.errors)} />
            <MutationError
              active={createProviderMutation.isError}
              message="Provider was not created."
            />
            <Button type="submit" disabled={createProviderMutation.isPending}>
              {createProviderMutation.isPending ? "Creating..." : "Create provider"}
            </Button>
          </form>
          <ProviderList providers={providers} isLoading={providersQuery.isPending} />
        </Panel>

        <Panel title="Projects" description="Projects own provider and model access.">
          <form
            className="grid gap-3"
            onSubmit={projectForm.handleSubmit((values) =>
              createProjectMutation.mutate({
                data: {
                  name: values.name,
                  description: values.description || null,
                },
              }),
            )}
          >
            <TextInput label="Name" registration={projectForm.register("name")} />
            <label className="block text-sm font-medium">
              Description
              <textarea
                className="mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                {...projectForm.register("description")}
              />
            </label>
            <FormError message={firstError(projectForm.formState.errors)} />
            <MutationError
              active={createProjectMutation.isError}
              message="Project was not created."
            />
            <Button type="submit" disabled={createProjectMutation.isPending}>
              {createProjectMutation.isPending ? "Creating..." : "Create project"}
            </Button>
          </form>
          <div className="mt-5 space-y-2">
            {projectsQuery.isPending ? (
              <p className="text-sm text-muted-foreground">Loading projects...</p>
            ) : null}
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
                data-active={project.id === effectiveProjectId}
                onClick={() => void setSelectedProjectId(project.id)}
              >
                <span>
                  <span className="block font-medium">{project.name}</span>
                  <span className="text-muted-foreground">
                    {project.description || "No description"}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">
                  {project.is_active ? "Active" : "Inactive"}
                </span>
              </button>
            ))}
          </div>
        </Panel>
      </section>

      <Panel
        title="Project provider access"
        description={
          selectedProject
            ? `Access rules for ${selectedProject.name}. Empty model list means all models.`
            : "Create a project to attach providers."
        }
      >
        <form
          className="grid gap-3 md:grid-cols-[1fr_1fr_auto]"
          onSubmit={accessForm.handleSubmit((values) => {
            if (!effectiveProjectId) {
              return;
            }

            grantAccessMutation.mutate({
              projectId: effectiveProjectId,
              data: {
                provider_id: values.provider_id,
                allowed_models: parseModelList(values.allowed_models),
              },
            });
          })}
        >
          <label className="block text-sm font-medium">
            Provider
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              {...accessForm.register("provider_id")}
            >
              <option value="">Select provider</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <TextInput
            label="Allowed models"
            placeholder="gpt-5.4-mini, gpt-5.4"
            registration={accessForm.register("allowed_models")}
          />
          <div className="flex items-end">
            <Button type="submit" disabled={!effectiveProjectId || grantAccessMutation.isPending}>
              {grantAccessMutation.isPending ? "Granting..." : "Grant access"}
            </Button>
          </div>
        </form>
        <FormError message={firstError(accessForm.formState.errors)} />
        <MutationError
          active={grantAccessMutation.isError}
          message="Access rule was not created."
        />
        <AccessList
          accessRules={accessQuery.data?.status === 200 ? accessQuery.data.data : []}
          providers={providers}
          isLoading={accessQuery.isPending && Boolean(effectiveProjectId)}
        />
      </Panel>
    </div>
  );
}

function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-card p-5 text-card-foreground">
      <div className="mb-5">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

function TextInput({
  label,
  placeholder,
  type = "text",
  registration,
}: {
  label: string;
  placeholder?: string;
  type?: string;
  registration: UseFormRegisterReturn;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
        placeholder={placeholder}
        type={type}
        {...registration}
      />
    </label>
  );
}

function ProviderList({
  providers,
  isLoading,
}: {
  providers: ProviderResponse[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="mt-5 text-sm text-muted-foreground">Loading providers...</p>;
  }

  return (
    <div className="mt-5 space-y-2">
      {providers.map((provider) => (
        <div key={provider.id} className="rounded-md border px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-3">
            <p className="font-medium">{provider.name}</p>
            <span className="text-xs text-muted-foreground">
              {provider.is_active ? "Active" : "Inactive"}
            </span>
          </div>
          <p className="mt-1 truncate text-muted-foreground">{provider.base_url}</p>
        </div>
      ))}
      {providers.length === 0 ? (
        <p className="text-sm text-muted-foreground">No providers yet.</p>
      ) : null}
    </div>
  );
}

function AccessList({
  accessRules,
  providers,
  isLoading,
}: {
  accessRules: ProjectProviderAccessResponse[];
  providers: ProviderResponse[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <p className="mt-5 text-sm text-muted-foreground">Loading access rules...</p>;
  }

  return (
    <div className="mt-5 overflow-hidden rounded-md border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Provider</th>
            <th className="px-3 py-2 font-medium">Models</th>
          </tr>
        </thead>
        <tbody>
          {accessRules.map((accessRule) => (
            <tr key={accessRule.id} className="border-t">
              <td className="px-3 py-2">
                {providers.find((provider) => provider.id === accessRule.provider_id)?.name ??
                  accessRule.provider_id}
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {accessRule.allowed_models?.join(", ") ?? "All models"}
              </td>
            </tr>
          ))}
          {accessRules.length === 0 ? (
            <tr>
              <td className="px-3 py-3 text-muted-foreground" colSpan={2}>
                No provider access rules for this project.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function parseModelList(value: string | undefined) {
  const models = value
    ?.split(",")
    .map((model) => model.trim())
    .filter(Boolean);

  return models && models.length > 0 ? models : null;
}

function firstError(errors: Record<string, { message?: string } | undefined>) {
  return Object.values(errors)[0]?.message;
}

function FormError({ message }: { message?: string }) {
  return message ? <p className="text-sm text-destructive">{message}</p> : null;
}

function MutationError({ active, message }: { active: boolean; message: string }) {
  return active ? <p className="text-sm text-destructive">{message}</p> : null;
}
