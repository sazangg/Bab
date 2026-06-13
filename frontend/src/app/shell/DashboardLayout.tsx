import {
  Activity,
  Building2,
  ChartNoAxesCombined,
  ClipboardList,
  FolderKanban,
  Gauge,
  KeyRound,
  LoaderCircle,
  LogOut,
  Moon,
  Palette,
  Plug,
  RefreshCw,
  Route,
  Settings,
  ShieldCheck,
  Sun,
  TerminalSquare,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, forwardRef, type ComponentProps } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  useLogoutApiV1AuthLogoutPost,
  useMeApiV1AuthMeGet,
} from "@/shared/api/generated/auth/auth";
import { useRuntimeInfoApiV1RuntimeInfoGet } from "@/shared/api/generated/health/health";
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
  useSidebar,
} from "@/components/ui/sidebar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  canViewActivity,
  canManageKeys,
  canViewDashboardHome,
  canViewUsage,
  hasAnyDirectTeamMembership,
  hasAnyProjectAdminMembership,
  hasAnyTeamMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import { useAuthStore } from "@/features/auth/model/auth-store";
import { useBreadcrumbs } from "@/app/shell/breadcrumbs";
import {
  formatMigrationStatus,
  resolveGatewayStatus,
  type ReadinessResponse,
} from "@/app/shell/operational-status";
import { useGatewayMetadata } from "@/shared/api/gateway-metadata";
import { httpClient } from "@/shared/api/http-client";
import type { AuthenticatedUser } from "@/shared/api/generated/schemas";

const organizationNav = [
  { to: "/", label: "Home", icon: Gauge, end: true },
  { to: "/providers", label: "Providers", icon: Plug, permission: "providers.view" },
  { to: "/usage", label: "Usage", icon: ChartNoAxesCombined, permission: "usage.view" },
  { to: "/activity", label: "Activity", icon: Activity, permission: "activity.view" },
  { to: "/audit", label: "Audit", icon: ClipboardList, permission: "audit.view" },
  { to: "/users", label: "Users", icon: Users, permission: "members.manage", scopedAdmin: true },
  { to: "/settings", label: "Settings", icon: Settings, permission: "settings.view" },
];

const workspaceNav = [
  { to: "/teams", label: "Teams", icon: Building2, permission: "teams.view", teamScoped: true },
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
    scopedAdmin: true,
  },
  {
    to: "/virtual-keys",
    label: "Virtual keys",
    icon: KeyRound,
    keyManager: true,
  },
  { to: "/playground", label: "Playground", icon: TerminalSquare, keyManager: true },
  {
    to: "/guardrails",
    label: "Guardrails",
    icon: ShieldCheck,
    permission: "guardrails.view",
    scopedAdmin: true,
  },
];

const internalNav = [{ to: "/design-system", label: "Design system", icon: Palette }];
const fallbackOrganizationName =
  import.meta.env.VITE_BAB_ORGANIZATION_NAME ?? "Default organization";
const isProductionBuild = import.meta.env.PROD;

function OrganizationLogo({ logoUrl }: { logoUrl?: string | null }) {
  const resolvedLogoUrl = logoUrl ? resolveAssetUrl(logoUrl) : null;
  return (
    <div className="flex size-7 shrink-0 items-center justify-center">
      {resolvedLogoUrl ? (
        <img src={resolvedLogoUrl} alt="" className="size-7 rounded-full object-cover" />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
        >
          B
        </span>
      )}
    </div>
  );
}

const SidebarNavigationLink = forwardRef<HTMLAnchorElement, ComponentProps<typeof Link>>(
  function SidebarNavigationLink({ to, onClick, children, ...props }, ref) {
    const { isMobile, setOpenMobile } = useSidebar();
    return (
      <Link
        ref={ref}
        to={to}
        onClick={(event) => {
          onClick?.(event);
          if (isMobile) setOpenMobile(false);
        }}
        {...props}
      >
        {children}
      </Link>
    );
  },
);

export function DashboardLayout() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const { resolvedTheme, setTheme } = useTheme();
  const metadataQuery = useGatewayMetadata();
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
  const generatedRuntimeInfoQuery = useRuntimeInfoApiV1RuntimeInfoGet({
    query: { staleTime: 300_000 },
  });
  const metadata = metadataQuery.data?.status === 200 ? metadataQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canView = (permission?: string) => !permission || hasPermission(currentUser, permission);
  const canViewWorkspaceItem = (item: (typeof workspaceNav)[number]) => {
    if (item.keyManager) return canManageKeys(currentUser);
    if (item.scopedAdmin) {
      return (
        canView(item.permission) ||
        hasAnyTeamAdminMembership(currentUser) ||
        hasAnyProjectAdminMembership(currentUser)
      );
    }
    if (item.teamScoped) {
      return canView(item.permission) || hasAnyDirectTeamMembership(currentUser);
    }
    if (item.scoped) return canView(item.permission) || hasAnyTeamMembership(currentUser);
    return canView(item.permission);
  };
  const visibleOrganizationNav = organizationNav.filter((item) => {
    if (item.to === "/") return canViewDashboardHome(currentUser);
    if (item.scopedAdmin) {
      return (
        canView(item.permission) ||
        hasAnyTeamAdminMembership(currentUser) ||
        hasAnyProjectAdminMembership(currentUser)
      );
    }
    if (item.to === "/usage") return canViewUsage(currentUser);
    if (item.to === "/activity") return canViewActivity(currentUser);
    return canView(item.permission);
  });
  const visibleWorkspaceNav = workspaceNav.filter((item) => {
    return canViewWorkspaceItem(item);
  });
  const showApiDocs = canManageKeys(currentUser);
  const visibleInternalNav = isProductionBuild ? [] : internalNav;
  const organizationName = metadata?.organization_name ?? fallbackOrganizationName;
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
  const gatewayStatus = resolveGatewayStatus(
    readinessQuery.data?.status,
    readinessQuery.data?.data,
  );
  const runtimeInfo =
    generatedRuntimeInfoQuery.data?.status === 200
      ? generatedRuntimeInfoQuery.data.data
      : undefined;
  const canViewRuntimeDetails =
    currentUser?.role === "org_owner" || currentUser?.role === "org_admin";

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
      <header className="fixed inset-x-0 top-0 z-30 flex h-12 items-center border-b bg-sidebar px-3 sm:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <SidebarTrigger aria-label="Toggle navigation" className="size-11 md:size-7" />
            </TooltipTrigger>
            <TooltipContent>Toggle navigation</TooltipContent>
          </Tooltip>
          <OrganizationLogo logoUrl={metadata?.organization_logo_url} />
          <span className="shrink-0 font-semibold">Bab</span>
          <span className="hidden max-w-48 truncate text-sm text-muted-foreground md:inline">
            {organizationName}
          </span>
          <span className="hidden text-muted-foreground md:inline">/</span>
          <span className="min-w-0 truncate text-sm text-muted-foreground md:hidden">
            {breadcrumbs.at(-1)?.label}
          </span>
          <Breadcrumb className="hidden min-w-0 md:block">
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
            <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
              <Link to="/">Dashboard</Link>
            </Button>
          ) : null}
          {showApiDocs ? (
            <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
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
                <span className="block text-xs font-normal text-muted-foreground">
                  {formatScopedAccess(currentUser)}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              {canViewDashboardHome(currentUser) ? (
                <DropdownMenuItem asChild className="sm:hidden">
                  <Link to="/">Dashboard</Link>
                </DropdownMenuItem>
              ) : null}
              {showApiDocs ? (
                <DropdownMenuItem asChild className="sm:hidden">
                  <Link to="/api-docs">API Docs</Link>
                </DropdownMenuItem>
              ) : null}
              {canViewDashboardHome(currentUser) || showApiDocs ? (
                <DropdownMenuSeparator className="sm:hidden" />
              ) : null}
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
                        <SidebarNavigationLink to={item.to}>
                          <item.icon />
                          <span>{item.label}</span>
                        </SidebarNavigationLink>
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
                        <SidebarNavigationLink to={item.to}>
                          <item.icon />
                          <span>{item.label}</span>
                        </SidebarNavigationLink>
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
            {visibleInternalNav.map((item) => (
              <SidebarMenuItem key={item.to}>
                <SidebarMenuButton asChild isActive={isActive(item.to)} tooltip={item.label}>
                  <SidebarNavigationLink to={item.to}>
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarNavigationLink>
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
          <div className="px-4 py-5 sm:px-6 sm:py-6">
            <Outlet />
          </div>
        </div>
      </SidebarInset>
      <footer
        role="contentinfo"
        className="fixed inset-x-0 bottom-0 z-30 flex h-7 items-center justify-between border-t bg-sidebar px-3 text-xs text-muted-foreground"
      >
        <div role="status" aria-live="polite" aria-label={`System status: ${gatewayStatus.label}`}>
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="relative flex size-2 shrink-0" aria-hidden="true">
                  {gatewayStatus.variant === "ready" ? (
                    <span className="absolute inset-0 rounded-full bg-success/60 motion-safe:animate-ping" />
                  ) : null}
                  <span className={`relative size-2 rounded-full ${gatewayStatus.className}`} />
                </span>
                <span>{gatewayStatus.label}</span>
              </button>
            </PopoverTrigger>
            <PopoverContent side="top" align="start" className="w-80 text-xs">
              <div className="space-y-3">
                <div>
                  <div className="font-medium text-foreground">Readiness checks</div>
                  <div className="text-muted-foreground">
                    Last checked: {formatCheckedAt(readinessQuery.dataUpdatedAt)}
                  </div>
                </div>
                <div className="grid gap-2">
                  {Object.entries(readinessQuery.data?.data?.checks ?? {}).map(([name, check]) => (
                    <div key={name} className="grid gap-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="capitalize">{name.replace(/_/g, " ")}</span>
                        <span className={check.ok ? "text-success" : "text-warning"}>
                          {check.ok ? "OK" : "Needs attention"}
                        </span>
                      </div>
                      {canViewRuntimeDetails && !check.ok ? (
                        <ReadinessCheckDetails check={check} />
                      ) : null}
                    </div>
                  ))}
                  {!readinessQuery.data?.data?.checks ? (
                    <div className="text-muted-foreground">No readiness details available.</div>
                  ) : null}
                </div>
                {canViewRuntimeDetails && runtimeInfo ? (
                  <div className="border-t pt-3">
                    <div className="font-medium text-foreground">Runtime migrations</div>
                    <div className="mt-1 text-muted-foreground">
                      {formatMigrationStatus(runtimeInfo.migrations)}
                    </div>
                  </div>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  disabled={readinessQuery.isFetching || generatedRuntimeInfoQuery.isFetching}
                  onClick={() => {
                    void readinessQuery.refetch();
                    if (canViewRuntimeDetails) void generatedRuntimeInfoQuery.refetch();
                  }}
                >
                  {readinessQuery.isFetching ? (
                    <LoaderCircle className="animate-spin" data-icon="inline-start" />
                  ) : (
                    <RefreshCw data-icon="inline-start" />
                  )}
                  Refresh status
                </Button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
        <div className="flex items-center gap-3">
          <span className="tabular-nums">v{runtimeInfo?.app_version ?? "unknown"}</span>
          <span aria-hidden="true">·</span>
          <span>{formatEnvironment(runtimeInfo?.environment)}</span>
        </div>
      </footer>
    </SidebarProvider>
  );
}

function resolveAssetUrl(url: string): string | null {
  // Defense in depth alongside the backend logo-url validator: only ever hand an
  // http(s) (or app-relative) URL to <img src>, never javascript:/data: schemes.
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("//")) return null; // protocol-relative -> untrusted origin
  if (!url.startsWith("/")) return null; // not an app-relative asset path
  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl ? new URL(url, apiBaseUrl).toString() : url;
}

function formatRole(role?: string) {
  if (role === "org_owner") return "Org owner";
  if (role === "org_admin") return "Org admin";
  if (role === "org_viewer") return "Org viewer";
  if (role === "org_member") return "Org member";
  return "Unknown role";
}

function formatScopedAccess(user: AuthenticatedUser | null | undefined) {
  const teamAdminCount = (user?.team_memberships ?? []).filter(
    (membership) => membership.role === "team_admin",
  ).length;
  const teamMemberCount = (user?.team_memberships ?? []).filter(
    (membership) => membership.role === "team_member",
  ).length;
  const projectAdminCount = (user?.project_memberships ?? []).filter(
    (membership) => membership.role === "project_admin",
  ).length;
  const projectMemberCount = (user?.project_memberships ?? []).filter(
    (membership) => membership.role === "project_member",
  ).length;
  const parts = [
    teamAdminCount ? `${teamAdminCount} team admin` : null,
    teamMemberCount ? `${teamMemberCount} team member` : null,
    projectAdminCount ? `${projectAdminCount} project admin` : null,
    projectMemberCount ? `${projectMemberCount} project member` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "No scoped roles";
}

function formatEnvironment(environment?: string) {
  if (!environment) return "Environment unknown";
  return environment.charAt(0).toUpperCase() + environment.slice(1);
}

function formatCheckedAt(timestamp: number) {
  if (!timestamp) return "Never";
  return new Date(timestamp).toLocaleTimeString();
}

function ReadinessCheckDetails({ check }: { check: ReadinessResponse["checks"][string] }) {
  const details = [
    check.error ? `Error: ${check.error}` : null,
    check.current_revision ? `Current: ${check.current_revision}` : null,
    check.head_revision ? `Expected: ${check.head_revision}` : null,
  ].filter(Boolean);
  return details.length ? (
    <div className="grid gap-0.5 text-muted-foreground">
      {details.map((detail) => (
        <span key={detail}>{detail}</span>
      ))}
    </div>
  ) : (
    <span className="text-muted-foreground">The backend did not provide more detail.</span>
  );
}
