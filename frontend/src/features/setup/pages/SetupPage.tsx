import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { useCreateFirstAdminApiV1SetupPost } from "@/shared/api/generated/setup/setup";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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

  const firstError = Object.values(form.formState.errors)[0]?.message;

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardDescription>Bab</CardDescription>
        <CardTitle className="text-2xl">Create admin</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={form.handleSubmit((values) => setupMutation.mutate({ data: values }))}
        >
          <div className="space-y-1.5">
            <Label htmlFor="setup-org">Organization name</Label>
            <Input
              id="setup-org"
              autoComplete="organization"
              {...form.register("organization_name")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="setup-email">Admin email</Label>
            <Input id="setup-email" type="email" autoComplete="email" {...form.register("email")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="setup-password">Password</Label>
            <Input
              id="setup-password"
              type="password"
              autoComplete="new-password"
              {...form.register("password")}
            />
          </div>
          {firstError ? <p className="text-sm text-destructive">{firstError}</p> : null}
          {setupMutation.isError ? (
            <p className="text-sm text-destructive">Setup could not be completed.</p>
          ) : null}
          <Button type="submit" className="w-full" disabled={setupMutation.isPending}>
            {setupMutation.isPending ? "Creating admin..." : "Create admin"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
