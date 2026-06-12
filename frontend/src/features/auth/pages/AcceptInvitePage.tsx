import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isWithinBcryptByteLimit } from "@/features/auth/lib/password";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { httpClient } from "@/shared/api/http-client";
import { useAcceptInviteApiV1AuthInvitesAcceptPost } from "@/shared/api/generated/auth/auth";
import { useQuery } from "@tanstack/react-query";

const acceptInviteSchema = z
  .object({
    name: z.string().max(255).optional(),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .refine(isWithinBcryptByteLimit, "Password must be at most 72 UTF-8 bytes"),
    confirmPassword: z.string().min(1, "Confirm your password"),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type AcceptInviteValues = z.infer<typeof acceptInviteSchema>;
type InvitePreview = {
  email: string;
  organization_name: string;
  role: string;
  team_name: string | null;
  team_role: string | null;
  project_name: string | null;
  project_role: string | null;
  status: string;
  expires_at: string;
};

export function AcceptInvitePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const token = searchParams.get("token");
  const [showPassword, setShowPassword] = useState(false);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setSession = useAuthStore((state) => state.setSession);
  const form = useForm<AcceptInviteValues>({
    resolver: zodResolver(acceptInviteSchema),
    defaultValues: {
      name: "",
      password: "",
      confirmPassword: "",
    },
  });
  const previewQuery = useQuery({
    queryKey: ["invite-preview", token],
    enabled: Boolean(token),
    queryFn: async () => {
      const response = await httpClient.get<InvitePreview>("/api/v1/auth/invites/preview", {
        params: { token },
      });
      return response.data;
    },
    retry: false,
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
    <Card className="w-full max-w-lg">
      <CardHeader>
        <CardDescription>Bab</CardDescription>
        <CardTitle className="text-2xl">Create your Bab account</CardTitle>
        <CardDescription>
          Accept your invitation by creating the password you will use to sign in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!token ? (
          <p className="text-sm text-destructive">Invite token is missing.</p>
        ) : previewQuery.isPending ? (
          <p className="text-sm text-muted-foreground">Checking invite...</p>
        ) : previewQuery.isError ? (
          <InviteStateMessage
            title="Invite not found"
            description="Ask your administrator for a new invite link."
          />
        ) : previewQuery.data.status !== "pending" ? (
          <InviteStateMessage
            title={`Invite ${previewQuery.data.status}`}
            description={
              previewQuery.data.status === "accepted"
                ? "This invite has already been accepted. Sign in with the invited email."
                : "Ask your administrator for a new invite link."
            }
          />
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
            <InviteSummary preview={previewQuery.data} />
            <div className="space-y-1.5">
              <Label htmlFor="invite-name">Display name (optional)</Label>
              <Input
                id="invite-name"
                autoComplete="name"
                placeholder="Shown in admin screens; not used for sign-in"
                {...form.register("name")}
              />
              {form.formState.errors.name ? (
                <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-password">Password</Label>
              <div className="flex gap-2">
                <Input
                  id="invite-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  {...form.register("password")}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label={showPassword ? "Hide secret" : "Show secret"}
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? <EyeOff /> : <Eye />}
                </Button>
              </div>
              {form.formState.errors.password ? (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Use at least 8 characters. Very long Unicode passwords are limited to 72 bytes.
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-confirm-password">Confirm password</Label>
              <Input
                id="invite-confirm-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                {...form.register("confirmPassword")}
              />
              {form.formState.errors.confirmPassword ? (
                <p className="text-xs text-destructive">
                  {form.formState.errors.confirmPassword.message}
                </p>
              ) : null}
            </div>
            {acceptMutation.isError ? (
              <p className="text-sm text-destructive">Invite could not be accepted.</p>
            ) : null}
            <Button type="submit" disabled={acceptMutation.isPending}>
              {acceptMutation.isPending ? "Creating account..." : "Create account and sign in"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function InviteSummary({ preview }: { preview: InvitePreview }) {
  return (
    <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm">
      <div>
        <div className="text-xs font-medium uppercase text-muted-foreground">Sign-in email</div>
        <div className="font-medium">{preview.email}</div>
      </div>
      <div>
        <div className="text-xs font-medium uppercase text-muted-foreground">Organization</div>
        <div>{preview.organization_name}</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline">{formatOrgRole(preview.role)}</Badge>
        {preview.team_name ? (
          <Badge variant="outline">
            {preview.team_name} · {formatScopedRole(preview.team_role)}
          </Badge>
        ) : null}
        {preview.project_name ? (
          <Badge variant="outline">
            {preview.project_name} · {formatScopedRole(preview.project_role)}
          </Badge>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        Invite expires {new Date(preview.expires_at).toLocaleString()}.
      </p>
    </div>
  );
}

function InviteStateMessage({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
      <p className="text-sm font-medium text-destructive">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function formatOrgRole(value: string) {
  if (value === "org_owner") return "Org owner";
  if (value === "org_admin") return "Org admin";
  if (value === "org_viewer") return "Org viewer";
  return "Org member";
}

function formatScopedRole(value: string | null) {
  if (value === "team_admin") return "Team admin";
  if (value === "team_member") return "Team member";
  if (value === "project_admin") return "Project admin";
  if (value === "project_member") return "Project member";
  return "Scoped role";
}
