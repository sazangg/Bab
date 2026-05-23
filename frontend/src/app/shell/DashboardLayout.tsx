import {
  Activity,
  Building2,
  ChartNoAxesCombined,
  FolderKanban,
  Gauge,
  LogOut,
  Moon,
  Palette,
  Plug,
  Route,
  Settings,
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
  useSidebar,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { useBreadcrumbs } from "@/app/shell/breadcrumbs";

const organizationNav = [
  { to: "/", label: "Home", icon: Gauge, end: true },
  { to: "/providers", label: "Providers", icon: Plug },
  { to: "/usage", label: "Usage", icon: ChartNoAxesCombined },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
];

const workspaceNav = [
  { to: "/teams", label: "Teams", icon: Building2 },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/allocations", label: "Allocations", icon: Route },
  { to: "/guardrails", label: "Guardrails", icon: ShieldCheck },
];

const internalNav = [{ to: "/design-system", label: "Design system", icon: Palette }];
const organizationName = import.meta.env.VITE_BAB_ORGANIZATION_NAME ?? "Default organization";

function LogoSidebarTrigger() {
  const { toggleSidebar, state } = useSidebar();
  const collapsed = state === "collapsed";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          aria-controls="primary-sidebar"
          className="group/logo -mx-2 flex size-11 cursor-pointer items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar"
        >
          <span
            aria-hidden="true"
            className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground transition-[opacity,transform] duration-150 group-hover/logo:opacity-90 group-active/logo:scale-95"
          >
            B
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent>{collapsed ? "Expand sidebar" : "Collapse sidebar"}</TooltipContent>
    </Tooltip>
  );
}

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

  const isActive = (path: string, end?: boolean) =>
    end || path === "/" ? location.pathname === path : location.pathname.startsWith(path);

  return (
    <SidebarProvider className="bab-dashboard-shell h-svh overflow-hidden bg-sidebar">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground focus:shadow-md focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-sidebar"
      >
        Skip to main content
      </a>
      <header className="fixed inset-x-0 top-0 z-30 flex h-12 items-center border-b bg-sidebar px-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <LogoSidebarTrigger />
          <span className="font-semibold">Bab</span>
          <span className="hidden max-w-48 truncate text-sm text-muted-foreground sm:inline">
            {organizationName}
          </span>
          <span className="hidden text-muted-foreground sm:inline">/</span>
          <Breadcrumb className="min-w-0">
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
      </header>
      <Sidebar collapsible="icon" id="primary-sidebar" aria-label="Primary navigation">
        <SidebarHeader className="h-12" />
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Organization</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {organizationNav.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(item.to, item.end)}
                      tooltip={item.label}
                    >
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
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {workspaceNav.map((item) => (
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
        </SidebarContent>
        <SidebarFooter className="mb-7 border-t p-2">
          <SidebarMenu>
            {internalNav.map((item) => (
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
        </SidebarFooter>
      </Sidebar>
      <SidebarInset
        id="main-content"
        aria-label="Main content"
        tabIndex={-1}
        className="mt-12 mb-7 min-h-[calc(100svh-4.75rem)] overflow-hidden bg-background focus:outline-none"
      >
        <div className="flex min-h-0 flex-1 flex-col overflow-auto">
          <div className="px-6 py-6">
            <Outlet />
          </div>
        </div>
      </SidebarInset>
      <footer
        role="contentinfo"
        className="fixed inset-x-0 bottom-0 z-30 flex h-7 items-center justify-between border-t bg-sidebar px-3 text-xs text-muted-foreground"
      >
        <div
          className="flex items-center gap-1.5"
          role="status"
          aria-live="polite"
          aria-label="System status: all systems operational"
        >
          <span className="relative flex size-2 shrink-0" aria-hidden="true">
            <span className="absolute inset-0 rounded-full bg-emerald-500/60 motion-safe:animate-ping" />
            <span className="relative size-2 rounded-full bg-emerald-500" />
          </span>
          <span>All systems operational</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="tabular-nums">v0.1.0</span>
          <span aria-hidden="true">·</span>
          <span>Local development</span>
        </div>
      </footer>
    </SidebarProvider>
  );
}
