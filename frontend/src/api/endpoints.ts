import type { ApiClient } from "./client";
import type {
  AuditEntry,
  ConnectionOut,
  DashboardItemOut,
  DashboardOut,
  DashboardSummary,
  FeedbackOut,
  FrequentQuestion,
  Preferences,
  ReadyResponse,
  RunCreated,
  RunOut,
  RunSummary,
  TokenResponse,
  User,
} from "./types";

export function login(api: ApiClient, email: string, password: string): Promise<TokenResponse> {
  return api.request("/api/auth/login", { method: "POST", body: { email, password }, anonymous: true });
}

export function refreshSession(api: ApiClient): Promise<TokenResponse> {
  return api.request("/api/auth/refresh", { method: "POST", anonymous: true, keepalive: true });
}

export function logout(api: ApiClient): Promise<void> {
  return api.request("/api/auth/logout", { method: "POST", anonymous: true, keepalive: true });
}

export function me(api: ApiClient): Promise<User> {
  return api.request("/api/auth/me");
}

export function readiness(api: ApiClient, signal?: AbortSignal): Promise<ReadyResponse> {
  return api.request("/api/health/ready", { anonymous: true, ...(signal ? { signal } : {}) });
}

export function startRun(api: ApiClient, question: string, conversationId: string | null): Promise<RunCreated> {
  return api.request("/api/runs", {
    method: "POST",
    body: conversationId ? { question, conversation_id: conversationId } : { question },
  });
}

export function cancelRun(api: ApiClient, runId: string): Promise<void> {
  return api.request(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export function getRun(api: ApiClient, runId: string, signal?: AbortSignal): Promise<RunOut> {
  return api.request(`/api/runs/${encodeURIComponent(runId)}`, signal ? { signal } : {});
}

export function listRuns(api: ApiClient, limit = 50): Promise<RunSummary[]> {
  return api.request(`/api/runs?limit=${limit}`);
}

export function sendFeedback(
  api: ApiClient,
  runId: string,
  body: { rating: "up" | "down"; comment?: string; verify?: boolean },
): Promise<FeedbackOut> {
  return api.request(`/api/runs/${encodeURIComponent(runId)}/feedback`, { method: "POST", body });
}

export function frequentQuestions(api: ApiClient): Promise<FrequentQuestion[]> {
  return api.request("/api/memory/frequent");
}

export function getPreferences(api: ApiClient): Promise<Preferences> {
  return api.request("/api/memory/preferences");
}

export function savePreferences(api: ApiClient, body: Preferences): Promise<Preferences> {
  return api.request("/api/memory/preferences", { method: "PUT", body });
}

export function listDashboards(api: ApiClient): Promise<DashboardSummary[]> {
  return api.request("/api/dashboards");
}

export function getDashboard(api: ApiClient, id: string): Promise<DashboardOut> {
  return api.request(`/api/dashboards/${encodeURIComponent(id)}`);
}

export function createDashboard(api: ApiClient, name: string, shared = false): Promise<DashboardSummary> {
  return api.request("/api/dashboards", { method: "POST", body: { name, shared } });
}

export function updateDashboard(
  api: ApiClient,
  id: string,
  body: { name?: string; shared?: boolean },
): Promise<DashboardSummary> {
  return api.request(`/api/dashboards/${encodeURIComponent(id)}`, { method: "PATCH", body });
}

export function deleteDashboard(api: ApiClient, id: string): Promise<void> {
  return api.request(`/api/dashboards/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function pinToDashboard(
  api: ApiClient,
  dashboardId: string,
  body: { run_id: string; step: number; title?: string },
): Promise<DashboardItemOut> {
  return api.request(`/api/dashboards/${encodeURIComponent(dashboardId)}/items`, { method: "POST", body });
}

export function unpinItem(api: ApiClient, dashboardId: string, itemId: string): Promise<void> {
  return api.request(
    `/api/dashboards/${encodeURIComponent(dashboardId)}/items/${encodeURIComponent(itemId)}`,
    { method: "DELETE" },
  );
}

export function reorderItems(api: ApiClient, dashboardId: string, itemIds: string[]): Promise<DashboardOut> {
  return api.request(`/api/dashboards/${encodeURIComponent(dashboardId)}/items/order`, {
    method: "PUT",
    body: { item_ids: itemIds },
  });
}

export function listConnections(api: ApiClient): Promise<ConnectionOut[]> {
  return api.request("/api/connections");
}

export function listAudit(
  api: ApiClient,
  params: { limit?: number; beforeId?: number | null; outcome?: string | null },
): Promise<AuditEntry[]> {
  const query = new URLSearchParams({ limit: String(params.limit ?? 50) });
  if (params.beforeId) query.set("before_id", String(params.beforeId));
  if (params.outcome) query.set("outcome", params.outcome);
  return api.request(`/api/audit?${query.toString()}`);
}
