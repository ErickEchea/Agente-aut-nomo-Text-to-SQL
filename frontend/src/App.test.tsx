import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

const readyBody = {
  status: "ready",
  version: "0.1.0",
  checks: {
    app_db: { ok: true, latency_ms: 3.2, detail: { extensions: ["pg_trgm", "unaccent", "vector"] } },
    demo_db: { ok: true, latency_ms: 4.1, detail: { read_only: true, retail_tables: 10 } },
    ollama: { ok: true, latency_ms: 8.9, detail: { required: ["qwen2.5-coder:7b"], missing: [] } },
  },
};

describe("App status page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows every dependency as operational when the API is ready", async () => {
    mockFetch(200, readyBody);
    render(<App />);
    expect(await screen.findByText("Operativo")).toBeInTheDocument();
    expect(screen.getByText("Base de datos retail (solo lectura)")).toBeInTheDocument();
    expect(screen.getAllByText(/^OK/)).toHaveLength(3);
  });

  it("shows the failing dependency when the API answers 503", async () => {
    mockFetch(503, {
      ...readyBody,
      status: "not_ready",
      checks: {
        ...readyBody.checks,
        ollama: {
          ok: false,
          latency_ms: 5,
          detail: { error: "required models not pulled", missing: ["qwen2.5-coder:7b"] },
        },
      },
    });
    render(<App />);
    expect(await screen.findByText("Degradado")).toBeInTheDocument();
    expect(screen.getByText(/Falla ·/)).toHaveTextContent("Falla · 5 ms");
  });

  it("explains how to recover when the API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No se puede contactar con la API");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
