/** Node-specific rendering of a timeline step's output (what the agent decided at that step). */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { NodeName } from "../../api/events";
import { usePreferences } from "../../app/preferences";
import { Badge } from "../../components/ui/primitives";
import { formatCell, formatDuration, kindForColumn } from "../../lib/format";
import { SqlBlock, SqlDiff } from "../results/SqlBlock";
import type { TimelineItem } from "./model";

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const text = (v: unknown): string => {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
};
const list = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x.length > 0) : [];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1">
      <dt className="label-micro">{label}</dt>
      <dd className="text-small text-fg-secondary">{children}</dd>
    </div>
  );
}

function Chips({ items, mono = true }: { items: string[]; mono?: boolean }) {
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((item) => (
        <li key={item} className={mono ? "rounded-sm bg-surface-3 px-1.5 py-0.5 font-mono text-[0.75rem] text-fg" : "text-fg"}>
          {item}
        </li>
      ))}
    </ul>
  );
}

function Preview({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const { locale } = usePreferences();
  const kinds = columns.map((c, i) => kindForColumn(c, rows.map((r) => r[i])));
  return (
    <div className="overflow-x-auto rounded-sm border border-line">
      <table className="w-full text-[0.75rem]">
        <thead className="bg-surface-2 text-fg-muted">
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col" className="px-2 py-1 text-left font-medium whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-t border-line">
              {row.map((value, c) => (
                <td key={c} className={typeof value === "number" ? "figures px-2 py-1 text-right" : "px-2 py-1 whitespace-nowrap"}>
                  {formatCell(value, locale, kinds[c] ?? "number")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Generic({ output }: { output: Record<string, unknown> }) {
  const entries = Object.entries(output).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <dl className="grid gap-2">
      {entries.map(([key, value]) => (
        <Field key={key} label={key.replace(/_/g, " ")}>
          {typeof value === "object" ? <code className="font-mono text-[0.75rem] break-all">{text(value)}</code> : text(value)}
        </Field>
      ))}
    </dl>
  );
}

export function NodeOutput({ item }: { item: TimelineItem }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const o = item.output;
  if (item.error) {
    return (
      <Field label={t("timeline.out.error")}>
        <span className="font-mono text-danger">{item.error}</span>
      </Field>
    );
  }
  if (!o) return null;
  const node: NodeName = item.node;

  switch (node) {
    case "understand":
      return (
        <dl className="grid gap-2">
          {str(o["intent"]) ? (
            <Field label={t("timeline.out.intent")}>
              <Badge tone={o["intent"] === "out_of_scope" ? "danger" : "accent"}>{String(o["intent"])}</Badge>
            </Field>
          ) : null}
          {str(o["standalone_question"]) ? <Field label={t("timeline.out.standaloneQuestion")}>{String(o["standalone_question"])}</Field> : null}
          {str(o["reason"]) ? <Field label={t("timeline.out.reason")}>{String(o["reason"])}</Field> : null}
          {str(o["guard"]) ? <Field label={t("timeline.out.guard")}>{String(o["guard"])}</Field> : null}
        </dl>
      );
    case "retrieve_schema": {
      const ranked = Array.isArray(o["ranked"]) ? (o["ranked"] as { table?: unknown; score?: unknown }[]) : [];
      const top = Math.max(...ranked.map((r) => num(r.score) ?? 0), 1e-9);
      return (
        <dl className="grid gap-3">
          <Field label={t("timeline.out.tables")}>
            <Chips items={list(o["tables"])} />
          </Field>
          {ranked.length > 0 ? (
            <Field label={t("timeline.out.ranked")}>
              <ul className="grid gap-1">
                {ranked.map((r) => (
                  <li key={String(r.table)} className="grid grid-cols-[9rem_1fr] items-center gap-2">
                    <span className="truncate font-mono text-[0.75rem] text-fg">{String(r.table)}</span>
                    <span className="h-1.5 rounded-full bg-surface-3">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(((num(r.score) ?? 0) / top) * 100)}%` }} />
                    </span>
                  </li>
                ))}
              </ul>
            </Field>
          ) : null}
          {list(o["joins"]).length > 0 ? (
            <Field label={t("timeline.out.joins")}>
              <ul className="grid gap-0.5 font-mono text-[0.75rem]">
                {list(o["joins"]).map((j) => (
                  <li key={j}>{j}</li>
                ))}
              </ul>
            </Field>
          ) : null}
          {list(o["terms"]).length > 0 ? (
            <Field label={t("timeline.out.terms")}>
              <Chips items={list(o["terms"])} />
            </Field>
          ) : null}
          {list(o["forced_tables"]).length > 0 ? (
            <Field label={t("timeline.out.forced")}>
              <Chips items={list(o["forced_tables"])} />
            </Field>
          ) : null}
          {list(o["examples"]).length > 0 ? (
            <Field label={t("timeline.out.examples")}>
              <ul className="grid gap-0.5">
                {list(o["examples"]).map((e) => (
                  <li key={e}>“{e}”</li>
                ))}
              </ul>
            </Field>
          ) : null}
        </dl>
      );
    }
    case "plan":
      return (
        <dl className="grid gap-2">
          {o["rejected"] ? <p className="text-small text-warning">{t("timeline.out.planRejected")}</p> : null}
          <Field label={t("timeline.out.steps")}>
            <ol className="grid list-decimal gap-0.5 pl-4">
              {list(o["steps"]).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </Field>
        </dl>
      );
    case "resolve_time":
      return (
        <dl className="grid gap-2">
          {list(o["ranges"]).length > 0 ? (
            <Field label={t("timeline.out.ranges")}>
              <ul className="grid gap-0.5">
                {list(o["ranges"]).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </Field>
          ) : null}
          {str(o["as_of"]) ? <Field label={t("timeline.out.asOf")}><span className="figures">{String(o["as_of"])}</span></Field> : null}
          {list(o["vague_terms"]).length > 0 ? (
            <Field label={t("timeline.out.vague")}>
              <Chips items={list(o["vague_terms"])} mono={false} />
            </Field>
          ) : null}
        </dl>
      );
    case "generate_sql":
    case "repair": {
      const error = o["error"] as { code?: unknown; message?: unknown } | undefined;
      return (
        <dl className="grid gap-3">
          {item.node === "repair" && item.previousSql && item.sql ? (
            <Field label={t("timeline.out.repairDiff")}>
              <SqlDiff before={item.previousSql} after={item.sql} />
            </Field>
          ) : item.sql ? (
            <SqlBlock sql={item.sql} compact copyable={false} />
          ) : null}
          {str(o["rationale"]) ? <Field label={t("timeline.out.rationale")}>{String(o["rationale"])}</Field> : null}
          {list(o["assumptions"]).length > 0 ? (
            <Field label={t("timeline.out.assumptions")}>
              <ul className="grid list-disc gap-0.5 pl-4">
                {list(o["assumptions"]).map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Field>
          ) : null}
          {error ? (
            <Field label={t("timeline.out.error")}>
              <span className="text-danger">
                <span className="font-mono">{String(error.code)}</span> · {String(error.message)}
              </span>
            </Field>
          ) : null}
        </dl>
      );
    }
    case "validate":
      return o["ok"] === false ? (
        <dl className="grid gap-2">
          <Field label={t("timeline.out.rejected")}>
            <span className="text-danger">
              <span className="font-mono">{String(o["code"])}</span> · {text(o["detail"])}
            </span>
          </Field>
        </dl>
      ) : (
        <dl className="grid gap-2">
          <Field label={t("timeline.out.valid")}>
            <Chips items={list(o["tables"])} />
          </Field>
          {num(o["limit"]) !== null ? <p className="label-micro">{t("timeline.out.limit", { limit: num(o["limit"]) })}</p> : null}
        </dl>
      );
    case "execute": {
      if (o["ok"] === false) {
        return (
          <Field label={t("timeline.out.error")}>
            <span className="text-danger">
              <span className="font-mono">{String(o["sqlstate"])}</span> · {text(o["message"])}
            </span>
          </Field>
        );
      }
      const columns = list(o["columns"]);
      const preview = Array.isArray(o["preview"]) ? (o["preview"] as unknown[][]) : [];
      return (
        <dl className="grid gap-2">
          <Field label={t("timeline.out.rows", { count: num(o["row_count"]) ?? 0 })}>
            <span className="figures">
              {formatDuration(num(o["duration_ms"]), locale)}
              {o["truncated"] ? ` · ${t("timeline.out.truncated")}` : ""}
            </span>
          </Field>
          {list(o["masked_columns"]).length > 0 ? (
            <Field label={t("timeline.out.masked")}>
              <Chips items={list(o["masked_columns"])} />
            </Field>
          ) : null}
          {columns.length > 0 && preview.length > 0 ? (
            <Field label={t("timeline.out.preview")}>
              <Preview columns={columns} rows={preview} />
            </Field>
          ) : null}
        </dl>
      );
    }
    case "verify_results":
      return o["ok"] === false ? (
        <Field label={t("timeline.out.issue")}>
          <span className="text-warning">
            <span className="font-mono">{String(o["code"])}</span> · {text(o["message"])}
          </span>
        </Field>
      ) : (
        <Generic output={o} />
      );
    case "visualize": {
      const charts = Array.isArray(o["charts"]) ? (o["charts"] as { kind?: unknown; reason?: unknown }[]) : [];
      return (
        <Field label={t("timeline.out.charts")}>
          <ul className="grid gap-1">
            {charts.map((c, i) => (
              <li key={i}>
                <Badge tone="info">{String(c.kind)}</Badge> <span>{text(c.reason)}</span>
              </li>
            ))}
          </ul>
        </Field>
      );
    }
    case "explain":
      return (
        <dl className="grid gap-2">
          <Field label={o["fallback"] ? t("timeline.out.fallback") : t("timeline.out.grounded")}>
            <Badge tone={o["fallback"] ? "warning" : "success"}>{o["fallback"] ? t("timeline.out.fallback") : t("timeline.out.grounded")}</Badge>
          </Field>
          {str(o["text"]) ? <Field label={t("results.tabs.explanation")}>{String(o["text"])}</Field> : null}
          {list(o["rejected_numbers"]).length > 0 ? (
            <Field label={t("timeline.out.rejectedNumbers")}>
              <Chips items={list(o["rejected_numbers"])} />
            </Field>
          ) : null}
        </dl>
      );
    case "remember":
      return <p className="text-small text-fg-secondary">{t("timeline.out.stored")}</p>;
    case "respond":
      return (
        <dl className="grid gap-2">
          <Field label={t("timeline.out.status")}>{t(`status.${String(o["status"])}`)}</Field>
          {str(o["answer"]) ? <Field label={t("results.tabs.explanation")}>{String(o["answer"])}</Field> : null}
        </dl>
      );
  }
}
