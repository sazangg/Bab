import {
  Activity,
  BookOpenText,
  Building2,
  ChartNoAxesCombined,
  ClipboardList,
  FolderKanban,
  Gauge,
  History,
  KeyRound,
  ListChecks,
  Palette,
  Plug,
  Route,
  Settings,
  ShieldCheck,
  TerminalSquare,
  Users,
  type LucideIcon,
} from "lucide-react";

import {
  canManageKeys,
  canViewActivity,
  canViewDashboardHome,
  canViewGatewayHistory,
  canViewSetup,
  canViewUsage,
  canViewWorkspace,
  hasAnyDirectTeamMembership,
  hasAnyProjectAdminMembership,
  hasAnyTeamAdminMembership,
  hasPermission,
} from "@/features/auth/lib/permissions";
import type { AuthenticatedUser } from "@/shared/api/generated/schemas";

export type NavigationGroupId =
  | "overview"
  | "workspace"
  | "ai_gateway"
  | "control"
  | "administration"
  | "internal";

export type NavigationItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  isVisible: (user: AuthenticatedUser | null | undefined) => boolean;
};

export type NavigationGroup = {
  id: NavigationGroupId;
  label: string;
  items: NavigationItem[];
};

const navigationGroups: NavigationGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [
      {
        to: "/",
        label: "Overview",
        icon: Gauge,
        end: true,
        isVisible: canViewDashboardHome,
      },
      {
        to: "/setup",
        label: "Setup",
        icon: ListChecks,
        isVisible: canViewSetup,
      },
    ],
  },
  {
    id: "workspace",
    label: "Workspace",
    items: [
      {
        to: "/teams",
        label: "Teams",
        icon: Building2,
        isVisible: (user) => hasPermission(user, "teams.view") || hasAnyDirectTeamMembership(user),
      },
      {
        to: "/projects",
        label: "Projects",
        icon: FolderKanban,
        isVisible: canViewWorkspace,
      },
      {
        to: "/virtual-keys",
        label: "Virtual keys",
        icon: KeyRound,
        isVisible: canManageKeys,
      },
    ],
  },
  {
    id: "ai_gateway",
    label: "AI Gateway",
    items: [
      {
        to: "/playground",
        label: "Playground",
        icon: TerminalSquare,
        isVisible: canManageKeys,
      },
      {
        to: "/gateway-history",
        label: "Gateway history",
        icon: History,
        isVisible: canViewGatewayHistory,
      },
      {
        to: "/usage",
        label: "Usage & cost",
        icon: ChartNoAxesCombined,
        isVisible: canViewUsage,
      },
      {
        to: "/api-docs",
        label: "API docs",
        icon: BookOpenText,
        isVisible: canManageKeys,
      },
    ],
  },
  {
    id: "control",
    label: "Control",
    items: [
      {
        to: "/providers",
        label: "Providers",
        icon: Plug,
        isVisible: (user) => hasPermission(user, "providers.view"),
      },
      {
        to: "/policies",
        label: "Policies",
        icon: Route,
        isVisible: (user) =>
          hasPermission(user, "policies.view") ||
          hasAnyTeamAdminMembership(user) ||
          hasAnyProjectAdminMembership(user),
      },
      {
        to: "/guardrails",
        label: "Guardrails",
        icon: ShieldCheck,
        isVisible: (user) =>
          hasPermission(user, "guardrails.view") ||
          hasAnyTeamAdminMembership(user) ||
          hasAnyProjectAdminMembership(user),
      },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    items: [
      {
        to: "/users",
        label: "Users",
        icon: Users,
        isVisible: (user) =>
          hasPermission(user, "members.manage") ||
          hasAnyTeamAdminMembership(user) ||
          hasAnyProjectAdminMembership(user),
      },
      {
        to: "/activity",
        label: "Activity",
        icon: Activity,
        isVisible: canViewActivity,
      },
      {
        to: "/audit",
        label: "Audit",
        icon: ClipboardList,
        isVisible: (user) => hasPermission(user, "audit.view"),
      },
      {
        to: "/settings",
        label: "Settings",
        icon: Settings,
        isVisible: (user) => hasPermission(user, "settings.view"),
      },
    ],
  },
  {
    id: "internal",
    label: "Internal",
    items: [
      {
        to: "/design-system",
        label: "Design system",
        icon: Palette,
        isVisible: () => true,
      },
    ],
  },
];

export function visibleNavigationGroups(
  user: AuthenticatedUser | null | undefined,
  options: { production?: boolean } = {},
): NavigationGroup[] {
  return navigationGroups
    .filter((group) => group.id !== "internal" || !options.production)
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.isVisible(user)),
    }))
    .filter((group) => group.items.length > 0);
}
