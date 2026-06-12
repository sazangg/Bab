import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { useLoginApiV1AuthLoginPost } from "@/shared/api/generated/auth/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthStore } from "@/features/auth/model/auth-store";

const loginSchema = z.object({
  email: z.email(),
  password: z.string().min(1),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [showPassword, setShowPassword] = useState(false);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setSession = useAuthStore((state) => state.setSession);
  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: "",
      password: "",
    },
  });
  const loginMutation = useLoginApiV1AuthLoginPost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 200) {
          queryClient.clear();
          setSession(response.data.access_token);
          const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;
          navigate(from && from !== "/login" ? from : "/", { replace: true });
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
        <CardTitle className="text-2xl">Sign in</CardTitle>
        <CardDescription>
          Use the email and password for your Bab organization account.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          autoComplete="on"
          onSubmit={form.handleSubmit((values) => loginMutation.mutate({ data: values }))}
        >
          <div className="space-y-1.5">
            <Label htmlFor="login-email">Email</Label>
            <Input
              id="login-email"
              type="email"
              autoComplete="username"
              {...form.register("email")}
            />
            {form.formState.errors.email ? (
              <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="login-password">Password</Label>
            <div className="flex gap-2">
              <Input
                id="login-password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
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
          </div>
          {loginMutation.isError ? (
            <p className="text-sm text-destructive">Invalid email or password.</p>
          ) : null}
          <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
            {loginMutation.isPending ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
