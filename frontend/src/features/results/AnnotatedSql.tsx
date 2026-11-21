/** Clause-by-clause explanation linked to the SQL: focusing a clause highlights its span. */
import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck } from "lucide-react";
import { useEffect, useState } from "react";
import type { ThemedToken } from "shiki/core";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import type { ClauseOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState } from "../../components/Page";
import { Badge, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { tokenizeSql } from "../../lib/highlight";

function useTokens(code: string | undefined): ThemedToken[][] | null {
  const [state, setState] = useState<{ code: string; lines: ThemedToken[][] } | null>(null);
  useEffect(() => {
    if (!code) return;
    let alive = true;
    tokenizeSql(code)
      .then((lines) => {
        if (alive) setState({ code, lines });
      })
      .catch(() => {
        // Plain text stays visible without highlighting.
      });
    return () => {
      alive = false;
    };
  }, [code]);
  return state !== null && state.code === code ? state.lines : null;
}

function clauseAt(clauses: ClauseOut[], offset: number): number {
  return clauses.findIndex((c) => offset >= c.start && offset < c.end);
}

function Code({ sql, clauses, active, onActive, label }: { sql: string; clauses: ClauseOut[]; active: number | null; onActive: (i: number | null) => void; label: string }) {
  const tokens = useTokens(sql);
  const current = active === null ? null : clauses[active];
  const lines = sql.split("\n");
  const starts = lines.reduce<number[]>((acc, _line, i) => {
    acc.push(i === 0 ? 0 : (acc[i - 1] ?? 0) + (lines[i - 1]?.length ?? 0) + 1);
    return acc;
  }, []);
  return (
    // Focusable so keyboard users can scroll long lines (axe: scrollable-region-focusable).
    <pre
      tabIndex={0}
      aria-label={label}
      className="sql-code min-w-0 overflow-x-auto rounded-md border border-line bg-surface-2 p-4"
      onMouseLeave={() => {
        onActive(null);
      }}
    >
      <code>
        {lines.map((line, i) => {
          const start = starts[i] ?? 0;
          const lineTokens = tokens?.[i] ?? [{ content: line, offset: start, color: undefined } as unknown as ThemedToken];
          return (
            <div key={i} className="whitespace-pre">
              {lineTokens.length === 0 ? " " : null}
              {lineTokens.map((token, j) => {
                const inside = current !== null && current !== undefined && token.offset >= current.start && token.offset < current.end;
                return (
                  <span
                    key={j}
                    style={{ color: token.color }}
                    onMouseEnter={() => {
                      const index = clauseAt(clauses, token.offset);
                      onActive(index >= 0 ? index : null);
                    }}
                    className={cn("transition-colors duration-[var(--duration-fast)]", inside && "rounded-[2px] bg-accent-soft")}
                  >
                    {token.content}
                  </span>
                );
              })}
            </div>
          );
        })}
      </code>
    </pre>
  );
}

export function AnnotatedSql({ runId, step }: { runId: string; step: number }) {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const [active, setActive] = useState<number | null>(null);
  const annotation = useQuery({
    queryKey: ["annotation", runId, step, locale],
    queryFn: () => endpoints.getAnnotation(api, runId, step, locale),
    staleTime: Infinity,
  });

  return (
    <section aria-labelledby={`annotated-${runId}-${step}`} className="grid min-w-0 grid-cols-1 gap-3">
      <div>
        <h3 id={`annotated-${runId}-${step}`} className="flex items-center gap-2 text-h3 text-fg">
          <BookOpenCheck aria-hidden="true" className="size-4 text-accent" />
          {t("results.annotatedTitle")}
        </h3>
        <p className="text-small text-fg-muted">{t("results.annotatedHint")}</p>
      </div>
      {annotation.isPending ? (
        <Skeleton className="h-48" />
      ) : annotation.isError ? (
        <ErrorState error={annotation.error} onRetry={() => void annotation.refetch()} />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="min-w-0 lg:sticky lg:top-0 lg:self-start">
            <Code sql={annotation.data.sql} clauses={annotation.data.clauses} active={active} onActive={setActive} label={t("results.annotatedTitle")} />
          </div>
          <ol className="grid content-start gap-2">
            {annotation.data.clauses.map((clause, i) => (
              <li key={`${clause.scope}-${clause.kind}-${clause.start}`}>
                <button
                  type="button"
                  aria-pressed={active === i}
                  onMouseEnter={() => {
                    setActive(i);
                  }}
                  onFocus={() => {
                    setActive(i);
                  }}
                  onBlur={() => {
                    setActive(null);
                  }}
                  className={cn(
                    "grid w-full gap-1 rounded-md border px-3 py-2 text-left transition-colors",
                    active === i ? "border-accent/60 bg-accent-soft" : "border-line bg-surface-1 hover:border-line-strong",
                    clause.scope && "ml-3 w-[calc(100%-0.75rem)]",
                  )}
                >
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-fg">{clause.title}</span>
                    {clause.scope && clause.kind !== "cte" ? (
                      <Badge>
                        {t("results.cte")} {clause.scope}
                      </Badge>
                    ) : null}
                  </span>
                  {clause.details.length > 0 ? (
                    <ul className="grid gap-0.5 text-small text-fg-secondary">
                      {clause.details.map((detail) => (
                        <li key={detail}>{detail}</li>
                      ))}
                    </ul>
                  ) : null}
                  {clause.rules.length > 0 ? (
                    <ul aria-label={t("results.rules")} className="grid gap-0.5">
                      {clause.rules.map((rule) => (
                        <li key={rule} className="text-small text-success">
                          {rule}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
