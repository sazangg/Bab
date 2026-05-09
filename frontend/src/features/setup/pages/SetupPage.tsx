import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { useCreateFirstAdminApiV1SetupPost } from "@/shared/api/generated/setup/setup";
import { Button } from "@/components/ui/button";

const setupSchema = z.object({
  organization_name: z.string().min(1).max(255),
  email: z.email(),
  password: z.string().min(12),
});

type SetupFormValues = z.infer<typeof setupSchema>;

export function SetupPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<SetupFormValues>({
    resolver: zodResolver(setupSchema),
    defaultValues: {
      organization_name: "",
      email: "",
      password: "",
    },
  });
  const setupMutation = useCreateFirstAdminApiV1SetupPost({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries();
        navigate("/login", { replace: true });
      },
    },
  });

  return (
    <section className="w-full max-w-sm rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">Bab</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-normal">Create admin</h1>
      <form
        className="mt-6 space-y-4"
        onSubmit={form.handleSubmit((values) => setupMutation.mutate({ data: values }))}
      >
        <label className="block text-sm font-medium">
          Organization name
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            autoComplete="organization"
            {...form.register("organization_name")}
          />
        </label>
        <label className="block text-sm font-medium">
          Admin email
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            type="email"
            autoComplete="email"
            {...form.register("email")}
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            type="password"
            autoComplete="new-password"
            {...form.register("password")}
          />
        </label>
        {Object.values(form.formState.errors)[0]?.message ? (
          <p className="text-sm text-destructive">
            {Object.values(form.formState.errors)[0]?.message}
          </p>
        ) : null}
        {setupMutation.isError ? (
          <p className="text-sm text-destructive">Setup could not be completed.</p>
        ) : null}
        <Button type="submit" className="w-full" disabled={setupMutation.isPending}>
          {setupMutation.isPending ? "Creating admin..." : "Create admin"}
        </Button>
      </form>
    </section>
  );
}
