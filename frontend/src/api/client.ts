/**
 * Thin fetch client. The access token lives only in memory (never in storage); on a 401 the client
 * asks the auth layer to refresh once (HttpOnly cookie) and retries the request.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly retryAfterS: number | null = null,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

/** The network itself failed (API down, offline). */
export class NetworkError extends Error {
  constructor() {
    super("network unreachable");
    this.name = "NetworkError";
  }
}

export interface AuthBridge {
  token: () => string | null;
  /** Obtain a fresh access token; resolves null when the session is gone. */
  refresh: () => Promise<string | null>;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Skip the Authorization header and the refresh-on-401 dance (login, refresh). */
  anonymous?: boolean;
  /**
   * Let the request finish even if the page navigates away. Used for refresh-token rotation: an
   * aborted rotation would leave the browser holding a token the server already replaced.
   */
  keepalive?: boolean;
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "validation error";
  } catch {
    // Non-JSON error body: fall through to the status text.
  }
  return response.statusText || "error";
}

export interface ApiClient {
  request: <T>(path: string, options?: RequestOptions) => Promise<T>;
  authHeaders: () => Promise<Record<string, string>>;
  /** Force a token refresh (e.g. an event stream got a 401); true when a session is still alive. */
  reauthenticate: () => Promise<boolean>;
}

export function createApiClient(auth: AuthBridge, fetchImpl: typeof fetch = fetch): ApiClient {
  async function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (token && !options.anonymous) headers["Authorization"] = `Bearer ${token}`;
    try {
      return await fetchImpl(path, {
        method: options.method ?? "GET",
        headers,
        credentials: "same-origin",
        signal: options.signal ?? null,
        keepalive: options.keepalive ?? false,
        ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new NetworkError();
    }
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    let response = await send(path, options, auth.token());
    if (response.status === 401 && !options.anonymous) {
      const fresh = await auth.refresh();
      if (fresh) response = await send(path, options, fresh);
    }
    if (!response.ok) {
      const retryAfter = response.headers.get("Retry-After");
      throw new ApiError(response.status, await detailOf(response), retryAfter ? Number(retryAfter) : null);
    }
    if (response.status === 204 || response.status === 202) {
      const text = await response.text();
      return (text ? JSON.parse(text) : undefined) as T;
    }
    return (await response.json()) as T;
  }

  async function authHeaders(): Promise<Record<string, string>> {
    const token = auth.token() ?? (await auth.refresh());
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function reauthenticate(): Promise<boolean> {
    return (await auth.refresh()) !== null;
  }

  return { request, authHeaders, reauthenticate };
}
