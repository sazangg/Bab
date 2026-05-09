import { Outlet } from "react-router-dom";

export function DashboardLayout() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl">
        <aside className="hidden w-64 border-r bg-sidebar px-4 py-6 lg:block">
          <p className="text-sm font-semibold tracking-normal text-sidebar-foreground">Bab</p>
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="border-b px-6 py-4">
            <p className="text-sm text-muted-foreground">Local dashboard</p>
          </header>
          <div className="flex-1 px-6 py-6">
            <Outlet />
          </div>
        </section>
      </div>
    </main>
  );
}
