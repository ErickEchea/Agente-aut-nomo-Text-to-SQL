import { z } from "zod";

const checkSchema = z.object({
  ok: z.boolean(),
  latency_ms: z.number(),
  detail: z.record(z.string(), z.unknown()),
});

export const readinessSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  version: z.string(),
  checks: z.record(z.string(), checkSchema),
});

export type Readiness = z.infer<typeof readinessSchema>;
export type DependencyCheck = z.infer<typeof checkSchema>;

export class ApiUnavailableError extends Error {
  readonly httpStatus: number | null;

  constructor(httpStatus: number | null) {
    super(httpStatus === null ? "API unreachable" : `API responded ${httpStatus}`);
    this.name = "ApiUnavailableError";
    this.httpStatus = httpStatus;
  }
}

/** GET /api/health/ready. A 503 still carries a valid body describing which dependency failed. */
export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  let response: Response;
  try {
    response = await fetch("/api/health/ready", {
      signal: signal ?? null,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiUnavailableError(null);
  }
  if (response.status !== 200 && response.status !== 503) {
    throw new ApiUnavailableError(response.status);
  }
  const parsed = readinessSchema.safeParse(await response.json());
  if (!parsed.success) throw new ApiUnavailableError(response.status);
  return parsed.data;
}
