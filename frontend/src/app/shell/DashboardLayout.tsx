import { Link, Outlet, useLocation } from "react-router-dom";

import { useLogoutApiV1AuthLogoutPost } from "@/shared/api/generated/auth/auth";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/features/auth/model/auth-store";

export function DashboardLayout() {
  const location = useLocation();
  const clearSession = useAuthStore((state) => state.clearSession);
  const logoutMutation = useLogoutApiV1AuthLogoutPost({
    mutation: {
      onSettled: () => {
        clearSession();
      },
    },
  });

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl">
        <aside className="hidden w-64 border-r bg-sidebar px-4 py-6 lg:block">
          <p className="text-sm font-semibold tracking-normal text-sidebar-foreground">Bab</p>
          <nav className="mt-6 space-y-1 text-sm text-sidebar-foreground">
            <NavLink to="/" label="Providers & projects" active={location.pathname === "/"} />
            <NavLink to="/keys" label="Virtual keys" active={location.pathname === "/keys"} />
            <NavLink to="/limits" label="Limits" active={location.pathname === "/limits"} />
            <NavLink to="/logs" label="Logs & analytics" active={location.pathname === "/logs"} />
          </nav>
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between border-b px-6 py-4">
            <p className="text-sm text-muted-foreground">Local dashboard</p>
            <Button
              type="button"
              variant="outline"
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
            >
              Logout
            </Button>
          </header>
          <div className="flex-1 px-6 py-6">
            <Outlet />
          </div>
        </section>
      </div>
    </main>
  );
}

function NavLink({ to, label, active }: { to: string; label: string; active: boolean }) {
  return (
    <Link
      to={to}
      className="block rounded-md px-3 py-2 data-[active=true]:bg-sidebar-accent"
      data-active={active}
    >
      {label}
    </Link>
  );
}
