import type { ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router";

import { LoginPage } from "../features/auth/LoginPage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";
import { AppShell } from "./AppShell";
import { RequireAdmin, RequireAuth, RouteError } from "./guards";

/** Secondary screens are code-split: the workspace loads first. */
function page(load: () => Promise<ComponentType>) {
  return { lazy: async () => ({ Component: await load() }), errorElement: <RouteError /> };
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  {
    element: <RequireAuth />,
    errorElement: <RouteError />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <WorkspacePage />, errorElement: <RouteError /> },
          { path: "dashboards", ...page(async () => (await import("../features/dashboards/DashboardsPage")).DashboardsPage) },
          { path: "dashboards/:id", ...page(async () => (await import("../features/dashboards/DashboardsPage")).DashboardPage) },
          { path: "history", ...page(async () => (await import("../features/history/HistoryPage")).HistoryPage) },
          { path: "connections", ...page(async () => (await import("../features/connections/ConnectionsPage")).ConnectionsPage) },
          { path: "benchmark", ...page(async () => (await import("../features/benchmark/BenchmarkPage")).BenchmarkPage) },
          {
            element: <RequireAdmin />,
            children: [{ path: "audit", ...page(async () => (await import("../features/admin/AuditPage")).AuditPage) }],
          },
          { path: "settings", ...page(async () => (await import("../features/settings/SettingsPage")).SettingsPage) },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
