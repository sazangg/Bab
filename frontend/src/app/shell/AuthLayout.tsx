import { Outlet } from "react-router-dom";

export function AuthLayout() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-10">
      <Outlet />
    </main>
  );
}
