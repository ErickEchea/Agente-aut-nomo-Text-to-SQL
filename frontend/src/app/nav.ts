import { Activity, Gauge, History, LayoutDashboard, MessageSquareText, Plug, ScrollText, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  key: "workspace" | "dashboards" | "history" | "connections" | "benchmark" | "audit" | "settings";
  icon: LucideIcon;
  adminOnly?: boolean;
}

export const NAV: NavItem[] = [
  { to: "/", key: "workspace", icon: MessageSquareText },
  { to: "/dashboards", key: "dashboards", icon: LayoutDashboard },
  { to: "/history", key: "history", icon: History },
  { to: "/connections", key: "connections", icon: Plug },
  { to: "/benchmark", key: "benchmark", icon: Gauge },
  { to: "/audit", key: "audit", icon: ScrollText, adminOnly: true },
  { to: "/settings", key: "settings", icon: Settings },
];

export const HEALTH_ICON = Activity;
