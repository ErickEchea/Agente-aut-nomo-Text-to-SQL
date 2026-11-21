import { describe, expect, it } from "vitest";

import { parseRunEvent, type RunEvent } from "../../api/events";
import { buildTimeline, pendingNodes } from "./model";

let seq = 0;
function ev(type: string, data: Record<string, unknown>): RunEvent {
  seq += 1;
  const event = parseRunEvent(type, JSON.stringify({ ts: "2026-11-21T10:00:00Z", ...data }), seq);
  if (!event) throw new Error(`invalid test event ${type}`);
  return event;
}

const done = (node: string, output: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) =>
  ev("node.completed", { node, step: 0, attempt: 1, duration_ms: 12.5, tokens: { prompt: 10, completion: 5 }, output, ...extra });

describe("buildTimeline", () => {
  it("pairs started/completed events and sums tokens", () => {
    const model = buildTimeline([
      ev("run.started", { run_id: "r", question: "¿Ventas?" }),
      ev("node.started", { node: "understand", step: 0, attempt: 1 }),
      done("understand", { intent: "data" }),
      ev("node.started", { node: "retrieve_schema", step: 0, attempt: 1 }),
    ]);
    expect(model.question).toBe("¿Ventas?");
    expect(model.items.map((i) => [i.node, i.state])).toEqual([
      ["understand", "done"],
      ["retrieve_schema", "running"],
    ]);
    expect(model.totalTokens).toBe(15);
    expect(pendingNodes(model)[0]).toBe("plan");
  });

  it("marks rejected SQL as an issue and builds the repair diff from the previous attempt", () => {
    const model = buildTimeline([
      ev("node.started", { node: "generate_sql", step: 0, attempt: 1 }),
      done("generate_sql", { step: 0, attempt: 1, sql: "SELECT 1 FROM ventas" }),
      ev("node.started", { node: "validate", step: 0, attempt: 1 }),
      done("validate", { ok: false, code: "glossary", detail: "returns" }),
      ev("node.started", { node: "repair", step: 0, attempt: 1 }),
      done("repair", { step: 0, attempt: 2, sql: "SELECT 2 FROM ventas" }),
      ev("node.started", { node: "repair", step: 0, attempt: 2 }),
      done("repair", { step: 0, attempt: 3, sql: "SELECT 3 FROM ventas", previous_sql: "SELECT 2.5 FROM ventas" }),
    ]);
    const [, validate, repair] = model.items;
    expect(validate?.state).toBe("issue");
    expect(repair?.previousSql).toBe("SELECT 1 FROM ventas");
    expect(repair?.sql).toBe("SELECT 2 FROM ventas");
    expect(repair?.attempt).toBe(2);
    expect(model.items[3]?.previousSql).toBe("SELECT 2.5 FROM ventas"); // the server's value wins
    expect(pendingNodes(model)).toEqual([]);
  });

  it("flags a plan the guard rejected", () => {
    const model = buildTimeline([
      ev("node.started", { node: "plan", step: 0, attempt: 1 }),
      done("plan", { rejected: "sql_in_plan", steps: ["q"] }),
    ]);
    expect(model.items[0]?.state).toBe("issue");
  });

  it("marks failed nodes and interrupted ones when the run ends", () => {
    const model = buildTimeline([
      ev("node.started", { node: "execute", step: 0, attempt: 1 }),
      ev("node.failed", { node: "execute", step: 0, attempt: 1, duration_ms: 3, error: "TimeoutError" }),
      ev("node.started", { node: "explain", step: 0, attempt: 1 }),
      ev("run.completed", { run_id: "r", status: "cancelled", answer: "", duration_ms: 900 }),
    ]);
    expect(model.items.map((i) => i.state)).toEqual(["failed", "failed"]);
    expect(model.items[0]?.error).toBe("TimeoutError");
    expect(model.finished).toBe(true);
    expect(model.status).toBe("cancelled");
    expect(model.totalMs).toBe(900);
    expect(pendingNodes(model)).toEqual([]);
  });

  it("drops malformed or unknown events", () => {
    expect(parseRunEvent("node.started", "{not json", 1)).toBeNull();
    expect(parseRunEvent("node.started", JSON.stringify({ node: "hack", ts: "x" }), 1)).toBeNull();
    expect(parseRunEvent("something.else", "{}", 1)).toBeNull();
  });
});
