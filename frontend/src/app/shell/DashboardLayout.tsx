import {
  BarChart3,
  ChevronsUpDown,
  Gauge,
  Landmark,
  LayoutDashboard,
  LogOut,
  Moon,
  Plug,
  ScrollText,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { useTheme } from "next-themes";
import { Fragment } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useLogoutApiV1AuthLogoutPost } from "@/shared/api/generated/auth/auth";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { useBreadcrumbs } from "@/app/shell/breadcrumbs";

const primaryNav = [
  { to: "/", label: "Summary", icon: LayoutDashboard },
  { to: "/providers", label: "Providers", icon: Plug },
];

const upcomingNav = [
  { label: "Allocations", icon: Landmark },
  { label: "Projects", icon: Landmark },
  { label: "Usage", icon: BarChart3 },
  { label: "Limits", icon: Gauge },
  { label: "Audit logs", icon: ScrollText },
  { label: "Security", icon: ShieldCheck },
];

export function DashboardLayout() {
  const location = useLocation();
  const { resolvedTheme, setTheme } = useTheme();
  const clearSession = useAuthStore((state) => state.clearSession);
  const logoutMutation = useLogoutApiV1AuthLogoutPost({
    mutation: {
      onSettled: () => {
        clearSession();
      },
    },
  });
  const breadcrumbs = useBreadcrumbs();
  const isDark = resolvedTheme === "dark";

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  return (
    <SidebarProvider className="bab-dashboard-shell h-svh overflow-hidden">
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center border-b bg-background px-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            B
          </div>
          <span className="font-semibold">Bab</span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="max-w-48">
                <span className="truncate">Default organization</span>
                <ChevronsUpDown data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel>Organization</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>Default organization</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <span className="text-muted-foreground">/</span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="max-w-40">
                <span className="truncate">Admin view</span>
                <ChevronsUpDown data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-48">
              <DropdownMenuLabel>View</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>Admin view</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link to="/">Dashboard</Link>
          </Button>
          <Button variant="ghost" size="sm" disabled>
            API Docs
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => setTheme(isDark ? "light" : "dark")}
                aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
              >
                {isDark ? <Sun /> : <Moon />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{isDark ? "Light mode" : "Dark mode"}</TooltipContent>
          </Tooltip>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon-sm" aria-label="Open account menu">
                A
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="bottom" align="end" className="w-56">
              <DropdownMenuLabel>Account</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => logoutMutation.mutate()}
                disabled={logoutMutation.isPending}
              >
                <LogOut data-icon="inline-start" />
                Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <Sidebar collapsible="icon">
        <SidebarHeader className="h-14" />
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {primaryNav.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={isActive(item.to)} tooltip={item.label}>
                      <Link to={item.to}>
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
          <SidebarGroup>
            <SidebarGroupLabel>Admin</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {upcomingNav.map((item) => (
                  <SidebarMenuItem key={item.label}>
                    <SidebarMenuButton disabled tooltip={`${item.label} - not available yet`}>
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton disabled>
                <span className="text-xs text-muted-foreground">Local development</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="mt-14 min-h-[calc(100svh-3.5rem)] bg-muted/30">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b bg-background px-4">
          <SidebarTrigger />
          <Breadcrumb>
            <BreadcrumbList>
              {breadcrumbs.map((crumb, index) => {
                const isLast = index === breadcrumbs.length - 1;
                return (
                  <Fragment key={`${crumb.label}-${index}`}>
                    <BreadcrumbItem>
                      {isLast || !crumb.to ? (
                        <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                      ) : (
                        <BreadcrumbLink asChild>
                          <Link to={crumb.to}>{crumb.label}</Link>
                        </BreadcrumbLink>
                      )}
                    </BreadcrumbItem>
                    {!isLast ? <BreadcrumbSeparator /> : null}
                  </Fragment>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
        </header>
        <div className="flex min-h-0 flex-1 flex-col p-3">
          <main className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-background">
            <div className="min-h-0 flex-1 overflow-auto p-6">
              <Outlet />
            </div>
          </main>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
