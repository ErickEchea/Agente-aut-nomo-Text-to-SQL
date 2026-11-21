/**
 * Agent run events (ADR-0009). SSE payloads are not part of OpenAPI, so they are validated here with
 * zod; an unknown or malformed event is dropped rather than crashing the timeline.
 */
import { z } from "zod";

export const NODE_NAMES = [
  "understand",
  "retrieve_schema",
  "plan",
  "resolve_time",
  "generate_sql",
  "validate",
  "execute",
  "verify_results",
  "repair",
  "visualize",
  "explain",
  "remember",
  "respond",
] as const;

export type NodeName = (typeof NODE_NAMES)[number];

const nodeMeta = {
  node: z.enum(NODE_NAMES),
  step: z.number().int().nullable().optional(),
  attempt: z.number().int().nullable().optional(),
  ts: z.string(),
};

export const runStarted = z.object({ run_id: z.string(), question: z.string(), ts: z.string() });
export const nodeStarted = z.object(nodeMeta);
export const nodeCompleted = z.object({
  ...nodeMeta,
  duration_ms: z.number(),
  tokens: z.object({ prompt: z.number(), completion: z.number() }),
  output: z.record(z.string(), z.unknown()),
});
export const nodeFailed = z.object({ ...nodeMeta, duration_ms: z.number(), error: z.string() });
export const runCompleted = z.object({
  run_id: z.string(),
  status: z.enum(["answered", "clarification", "refused", "failed", "cancelled"]),
  answer: z.string(),
  duration_ms: z.number().nullable().optional(),
  ts: z.string(),
});

export type RunEvent =
  | { seq: number; type: "run.started"; data: z.infer<typeof runStarted> }
  | { seq: number; type: "node.started"; data: z.infer<typeof nodeStarted> }
  | { seq: number; type: "node.completed"; data: z.infer<typeof nodeCompleted> }
  | { seq: number; type: "node.failed"; data: z.infer<typeof nodeFailed> }
  | { seq: number; type: "run.completed"; data: z.infer<typeof runCompleted> };

export const TERMINAL_EVENT = "run.completed";

const SCHEMAS = {
  "run.started": runStarted,
  "node.started": nodeStarted,
  "node.completed": nodeCompleted,
  "node.failed": nodeFailed,
  "run.completed": runCompleted,
} as const;

export function parseRunEvent(type: string, data: string, seq: number): RunEvent | null {
  if (!(type in SCHEMAS)) return null;
  let json: unknown;
  try {
    json = JSON.parse(data);
  } catch {
    return null;
  }
  const parsed = SCHEMAS[type as keyof typeof SCHEMAS].safeParse(json);
  return parsed.success ? ({ seq, type, data: parsed.data } as RunEvent) : null;
}
