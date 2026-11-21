/** Folds the agent's SSE events into timeline items (pure: unit-tested without a DOM). */
import type { NodeName, RunEvent } from "../../api/events";

export type ItemState = "pending" | "running" | "done" | "issue" | "failed";

export interface TimelineItem {
  key: string;
  node: NodeName;
  step: number | null;
  attempt: number | null;
  state: ItemState;
  startedAt: string | null;
  durationMs: number | null;
  tokens: number;
  output: Record<string, unknown> | null;
  error: string | null;
  /** For generate_sql/repair: the SQL produced and the SQL it replaces (repair diff). */
  sql: string | null;
  previousSql: string | null;
}

export interface TimelineModel {
  items: TimelineItem[];
  question: string | null;
  finished: boolean;
  status: string | null;
  totalMs: number | null;
  totalTokens: number;
}

/** The happy path, used to show what is still ahead while a run is live. */
export const MAIN_PATH: readonly NodeName[] = [
  "understand",
  "retrieve_schema",
  "plan",
  "resolve_time",
  "generate_sql",
  "validate",
  "execute",
  "verify_results",
  "visualize",
  "explain",
  "remember",
  "respond",
];

function issueOf(node: NodeName, output: Record<string, unknown>): boolean {
  if (output["ok"] === false || output["rejected"] !== undefined) return true;
  if ((node === "generate_sql" || node === "repair") && output["error"] !== undefined) return true;
  return false;
}

export function buildTimeline(events: readonly RunEvent[]): TimelineModel {
  const items: TimelineItem[] = [];
  let question: string | null = null;
  let finished = false;
  let status: string | null = null;
  let totalMs: number | null = null;
  let lastSql: string | null = null;

  const openItem = (node: NodeName): TimelineItem | undefined => {
    for (let i = items.length - 1; i >= 0; i--) {
      const item = items[i];
      if (item?.node === node && item.state === "running") return item;
    }
    return undefined;
  };

  for (const event of events) {
    switch (event.type) {
      case "run.started":
        question = event.data.question;
        break;
      case "node.started":
        items.push({
          key: `${event.seq}`,
          node: event.data.node,
          step: event.data.step ?? null,
          attempt: event.data.attempt ?? null,
          state: "running",
          startedAt: event.data.ts,
          durationMs: null,
          tokens: 0,
          output: null,
          error: null,
          sql: null,
          previousSql: null,
        });
        break;
      case "node.completed": {
        const item = openItem(event.data.node);
        if (!item) break;
        const output = event.data.output;
        item.durationMs = event.data.duration_ms;
        item.tokens = event.data.tokens.prompt + event.data.tokens.completion;
        item.output = output;
        item.state = issueOf(item.node, output) ? "issue" : "done";
        if (typeof output["attempt"] === "number") item.attempt = output["attempt"];
        const sql = typeof output["sql"] === "string" ? output["sql"] : null;
        if (item.node === "generate_sql" || item.node === "repair") {
          item.sql = sql;
          if (item.node === "repair") {
            const previous = output["previous_sql"];
            item.previousSql = typeof previous === "string" && previous ? previous : lastSql;
          }
          if (sql) lastSql = sql;
        }
        break;
      }
      case "node.failed": {
        const item = openItem(event.data.node);
        if (!item) break;
        item.state = "failed";
        item.durationMs = event.data.duration_ms;
        item.error = event.data.error;
        break;
      }
      case "run.completed":
        finished = true;
        status = event.data.status;
        totalMs = event.data.duration_ms ?? null;
        break;
    }
  }

  if (finished) {
    // A node still "running" after the end was interrupted (cancellation).
    for (const item of items) if (item.state === "running") item.state = "failed";
  }

  return {
    items,
    question,
    finished,
    status,
    totalMs,
    totalTokens: items.reduce((sum, item) => sum + item.tokens, 0),
  };
}

/** Main-path nodes not reached yet (shown ghosted while the run is live). */
export function pendingNodes(model: TimelineModel): NodeName[] {
  if (model.finished) return [];
  const last = model.items.at(-1);
  if (!last) return [...MAIN_PATH];
  if (last.node === "repair") return [];
  const index = MAIN_PATH.indexOf(last.node);
  return index < 0 ? [] : MAIN_PATH.slice(index + 1);
}
