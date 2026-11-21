import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, NetworkError } from "./client";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

describe("createApiClient", () => {
  it("sends the bearer token and JSON body", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(json(200, { ok: true }));
    const api = createApiClient({ token: () => "abc", refresh: () => Promise.resolve(null) }, fetchImpl);
    await api.request("/api/x", { method: "POST", body: { a: 1 } });
    const init = fetchImpl.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer abc");
    expect(init?.body).toBe('{"a":1}');
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(200, { value: 42 }));
    const refresh = vi.fn(() => Promise.resolve("fresh"));
    const api = createApiClient({ token: () => "old", refresh }, fetchImpl);
    await expect(api.request<{ value: number }>("/api/x")).resolves.toEqual({ value: 42 });
    expect(refresh).toHaveBeenCalledOnce();
    expect((fetchImpl.mock.calls[1]?.[1]?.headers as Record<string, string>)["Authorization"]).toBe("Bearer fresh");
  });

  it("maps errors: detail, Retry-After and network failures", async () => {
    const limited = createApiClient(
      { token: () => null, refresh: () => Promise.resolve(null) },
      vi.fn<typeof fetch>().mockResolvedValue(json(429, { detail: "too many requests" }, { "Retry-After": "9" })),
    );
    await expect(limited.request("/api/x")).rejects.toEqual(new ApiError(429, "too many requests", 9));

    const offline = createApiClient(
      { token: () => null, refresh: () => Promise.resolve(null) },
      vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(offline.request("/api/x")).rejects.toBeInstanceOf(NetworkError);
  });

  it("can keep a request alive across navigations", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(json(200, {}));
    const api = createApiClient({ token: () => null, refresh: () => Promise.resolve(null) }, fetchImpl);
    await api.request("/api/auth/refresh", { method: "POST", anonymous: true, keepalive: true });
    expect(fetchImpl.mock.calls[0]?.[1]?.keepalive).toBe(true);
  });

  it("returns undefined for empty 204/202 bodies", async () => {
    const api = createApiClient(
      { token: () => "t", refresh: () => Promise.resolve(null) },
      vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 })),
    );
    await expect(api.request("/api/x", { method: "DELETE" })).resolves.toBeUndefined();
  });
});
