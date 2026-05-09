import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { useLoginApiV1AuthLoginPost } from "@/shared/api/generated/auth/auth";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/features/auth/model/auth-store";

const loginSchema = z.object({
  email: z.email(),
  password: z.string().min(1),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
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
    <section className="w-full max-w-sm rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">Bab</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-normal">Sign in</h1>
      <form
        className="mt-6 space-y-4"
        onSubmit={form.handleSubmit((values) => loginMutation.mutate({ data: values }))}
      >
        <label className="block text-sm font-medium">
          Email
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            type="email"
            autoComplete="email"
            {...form.register("email")}
          />
        </label>
        {form.formState.errors.email ? (
          <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>
        ) : null}
        <label className="block text-sm font-medium">
          Password
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            type="password"
            autoComplete="current-password"
            {...form.register("password")}
          />
        </label>
        {loginMutation.isError ? (
          <p className="text-sm text-destructive">Invalid email or password.</p>
        ) : null}
        <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? "Signing in..." : "Sign in"}
        </Button>
      </form>
    </section>
  );
}
