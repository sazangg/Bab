import {
  Activity,
  Building2,
  ChartNoAxesCombined,
  ClipboardList,
  FolderKanban,
  Gauge,
  KeyRound,
  LogOut,
  Moon,
  Palette,
  Plug,
  Route,
  Settings,
  ShieldCheck,
  Sun,
  TerminalSquare,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  useLogoutApiV1AuthLogoutPost,
  useMeApiV1AuthMeGet,
} from "@/shared/api/generated/auth/auth";
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
import {
  canManageKeys,
  canViewDashboardHome,
  hasAnyTeamMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { useBreadcrumbs } from "@/app/shell/breadcrumbs";
import { useGetSettingsApiV1SettingsGet } from "@/shared/api/generated/settings/settings";
import { httpClient } from "@/shared/api/http-client";

const organizationNav = [
  { to: "/", label: "Home", icon: Gauge, end: true },
  { to: "/providers", label: "Providers", icon: Plug, permission: "providers.view" },
  { to: "/usage", label: "Usage", icon: ChartNoAxesCombined, permission: "usage.view" },
  { to: "/activity", label: "Activity", icon: Activity, permission: "activity.view" },
  { to: "/audit", label: "Audit", icon: ClipboardList, permission: "audit.view" },
  { to: "/users", label: "Users", icon: Users, permission: "members.manage" },
  { to: "/settings", label: "Settings", icon: Settings, permission: "settings.view" },
];

const workspaceNav = [
  { to: "/teams", label: "Teams", icon: Building2, permission: "teams.view", scoped: true },
  {
    to: "/projects",
    label: "Projects",
    icon: FolderKanban,
    permission: "projects.view",
    scoped: true,
  },
  {
    to: "/policies",
    label: "Policies",
    icon: Route,
    permission: "policies.view",
    scoped: true,
  },
  { to: "/virtual-keys", label: "Virtual keys", icon: KeyRound, keyManager: true },
  { to: "/playground", label: "Playground", icon: TerminalSquare, keyManager: true },
  { to: "/guardrails", label: "Guardrails", icon: ShieldCheck, permission: "guardrails.view" },
];

const internalNav = [{ to: "/design-system", label: "Design system", icon: Palette }];
const fallbackOrganizationName =
  import.meta.env.VITE_BAB_ORGANIZATION_NAME ?? "Default organization";

type ReadinessResponse = {
  status: "ready" | "not_ready";
  checks: Record<string, { ok: boolean }>;
};

function LogoSidebarTrigger({ logoUrl }: { logoUrl?: string | null }) {
  const { toggleSidebar, state } = useSidebar();
  const collapsed = state === "collapsed";
  const resolvedLogoUrl = logoUrl ? resolveAssetUrl(logoUrl) : null;
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
          {resolvedLogoUrl ? (
            <img
              src={resolvedLogoUrl}
              alt=""
              className="size-7 rounded-full object-cover transition-[opacity,transform] duration-150 group-hover/logo:opacity-90 group-active/logo:scale-95"
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground transition-[opacity,transform] duration-150 group-hover/logo:opacity-90 group-active/logo:scale-95"
            >
              B
            </span>
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent>{collapsed ? "Expand sidebar" : "Collapse sidebar"}</TooltipContent>
    </Tooltip>
  );
}

export function DashboardLayout() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const { resolvedTheme, setTheme } = useTheme();
  const settingsQuery = useGetSettingsApiV1SettingsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const readinessQuery = useQuery({
    queryKey: ["gateway-readiness"],
    queryFn: async () => {
      const response = await httpClient.get<ReadinessResponse>("/api/v1/ready", {
        validateStatus: () => true,
      });
      return { status: response.status, data: response.data };
    },
    refetchInterval: 30_000,
  });
  const settings = settingsQuery.data?.status === 200 ? settingsQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canView = (permission?: string) => !permission || hasPermission(currentUser, permission);
  const canViewWorkspaceItem = (item: (typeof workspaceNav)[number]) => {
    if (item.keyManager) return canManageKeys(currentUser);
    if (item.scoped) return canView(item.permission) || hasAnyTeamMembership(currentUser);
    return canView(item.permission);
  };
  const visibleOrganizationNav = organizationNav.filter((item) => {
    if (item.to === "/") return canViewDashboardHome(currentUser);
    return canView(item.permission);
  });
  const visibleWorkspaceNav = workspaceNav.filter((item) => {
    return canViewWorkspaceItem(item);
  });
  const showApiDocs = canManageKeys(currentUser) || hasPermission(currentUser, "providers.view");
  const organizationName = settings?.organization_name ?? fallbackOrganizationName;
  const clearSession = useAuthStore((state) => state.clearSession);
  const logoutMutation = useLogoutApiV1AuthLogoutPost({
    mutation: {
      onSettled: () => {
        clearSession();
        queryClient.clear();
      },
    },
  });
  const breadcrumbs = useBreadcrumbs();
  const isDark = resolvedTheme === "dark";
  const gatewayStatus = resolveGatewayStatus(readinessQuery.data?.status, readinessQuery.data?.data);

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
          <LogoSidebarTrigger logoUrl={settings?.organization_logo_url} />
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
          {canViewDashboardHome(currentUser) ? (
            <Button asChild variant="ghost" size="sm">
              <Link to="/">Dashboard</Link>
            </Button>
          ) : null}
          {showApiDocs ? (
            <Button asChild variant="ghost" size="sm">
              <Link to="/api-docs">API Docs</Link>
            </Button>
          ) : null}
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
              <DropdownMenuLabel>
                <span className="block truncate">{currentUser?.email ?? "Account"}</span>
                <span className="block text-xs font-normal text-muted-foreground">
                  {formatRole(currentUser?.role)}
                </span>
              </DropdownMenuLabel>
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
          {visibleOrganizationNav.length > 0 ? (
            <SidebarGroup>
              <SidebarGroupLabel>Organization</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {visibleOrganizationNav.map((item) => (
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
          ) : null}
          {visibleWorkspaceNav.length > 0 ? (
            <SidebarGroup>
              <SidebarGroupLabel>Workspace</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {visibleWorkspaceNav.map((item) => (
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
          ) : null}
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
          aria-label={`System status: ${gatewayStatus.label}`}
        >
          <span className="relative flex size-2 shrink-0" aria-hidden="true">
            {gatewayStatus.variant === "ready" ? (
              <span className="absolute inset-0 rounded-full bg-emerald-500/60 motion-safe:animate-ping" />
            ) : null}
            <span className={`relative size-2 rounded-full ${gatewayStatus.className}`} />
          </span>
          <span>{gatewayStatus.label}</span>
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

function resolveGatewayStatus(statusCode?: number, readiness?: ReadinessResponse) {
  if (!statusCode || !readiness) {
    return {
      label: "Status unavailable",
      variant: "unknown",
      className: "bg-muted-foreground",
    } as const;
  }
  if (statusCode === 200 && readiness.status === "ready") {
    return {
      label: "Gateway ready",
      variant: "ready",
      className: "bg-emerald-500",
    } as const;
  }
  return {
    label: "Gateway degraded",
    variant: "degraded",
    className: "bg-amber-500",
  } as const;
}

function resolveAssetUrl(url: string) {
  if (/^https?:\/\//i.test(url)) return url;
  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl ? new URL(url, apiBaseUrl).toString() : url;
}

function formatRole(role?: string) {
  if (role === "org_owner") return "Owner";
  if (role === "org_admin") return "Admin";
  if (role === "org_viewer") return "Viewer";
  if (role === "org_member") return "Member";
  return "Unknown role";
}
