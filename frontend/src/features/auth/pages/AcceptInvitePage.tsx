import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { isWithinBcryptByteLimit } from "@/features/auth/lib/password";
import { useAcceptInviteApiV1AuthInvitesAcceptPost } from "@/shared/api/generated/auth/auth";

const acceptInviteSchema = z.object({
  name: z.string().max(255).optional(),
  password: z
    .string()
    .min(8)
    .refine(isWithinBcryptByteLimit, "Password must be at most 72 UTF-8 bytes"),
});

type AcceptInviteValues = z.infer<typeof acceptInviteSchema>;

export function AcceptInvitePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const token = searchParams.get("token");
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setSession = useAuthStore((state) => state.setSession);
  const form = useForm<AcceptInviteValues>({
    resolver: zodResolver(acceptInviteSchema),
    defaultValues: {
      name: "",
      password: "",
    },
  });
  const acceptMutation = useAcceptInviteApiV1AuthInvitesAcceptPost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 200) {
          queryClient.clear();
          setSession(response.data.access_token);
          navigate("/", { replace: true });
        }
      },
    },
  });

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardDescription>Bab</CardDescription>
        <CardTitle className="text-2xl">Accept invite</CardTitle>
      </CardHeader>
      <CardContent>
        {!token ? (
          <p className="text-sm text-destructive">Invite token is missing.</p>
        ) : (
          <form
            className="grid gap-4"
            onSubmit={form.handleSubmit((values) =>
              acceptMutation.mutate({
                data: {
                  token: token ?? "",
                  name: values.name || null,
                  password: values.password,
                },
              }),
            )}
          >
            <div className="space-y-1.5">
              <Label htmlFor="invite-name">Name</Label>
              <Input id="invite-name" autoComplete="name" {...form.register("name")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-password">Password</Label>
              <Input
                id="invite-password"
                type="password"
                autoComplete="new-password"
                {...form.register("password")}
              />
              {form.formState.errors.password ? (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              ) : null}
            </div>
            {acceptMutation.isError ? (
              <p className="text-sm text-destructive">Invite could not be accepted.</p>
            ) : null}
            <Button type="submit" disabled={acceptMutation.isPending}>
              {acceptMutation.isPending ? "Accepting..." : "Accept invite"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
