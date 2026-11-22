/** Every golden question of one run: outcome, why it failed, latency, repairs and the SQL it ran. */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, XCircle } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import type { BenchmarkResultOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState } from "../../components/Page";
import { Badge, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { formatDuration } from "../../lib/format";
import { SqlBlock } from "../results/SqlBlock";
import { DIFFICULTIES } from "./model";

type Filter = "all" | "wrong";
const SELECT = "h-9 rounded-md border border-line-strong bg-surface-2 px-2 text-small text-fg focus-visible:border-accent";

function Row({ result }: { result: BenchmarkResultOut }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const Icon = result.correct ? CheckCircle2 : XCircle;
  return (
    <li className="border-b border-line last:border-b-0">
      <details className="group">
        <summary className="grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 px-3 py-2.5 select-none hover:bg-surface-2 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
          <Icon aria-hidden="true" className={cn("mt-0.5 size-4", result.correct ? "text-success" : "text-danger")} />
          <span className="grid min-w-0 gap-0.5">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-micro text-fg-muted">{result.item_id}</span>
              <span className="text-fg">{result.question}</span>
            </span>
            <span className="text-small text-fg-secondary">
              {t(`benchmark.reasons.${result.reason}`, { defaultValue: result.reason })}
              {result.repairs > 0 ? ` · ${t("benchmark.repairs", { count: result.repairs })}` : ""}
            </span>
          </span>
          <span className="col-start-2 flex items-center gap-2 sm:col-start-auto">
            <Badge>{t(`benchmark.difficulty.${result.difficulty}`, { defaultValue: result.difficulty })}</Badge>
            <span className="figures text-small text-fg-muted">{formatDuration(result.latency_ms, locale)}</span>
            <ChevronRight aria-hidden="true" className="size-4 text-fg-muted transition-transform group-open:rotate-90" />
          </span>
        </summary>
        <div className="grid min-w-0 gap-2 px-3 pb-3 sm:pl-10">
          {result.sql.length > 0 ? (
            result.sql.map((sql, i) => <SqlBlock key={i} sql={sql} compact />)
          ) : (
            <p className="text-small text-fg-muted">{result.error ?? t("benchmark.noSql")}</p>
          )}
        </div>
      </details>
    </li>
  );
}

export function QuestionResults({ runId, name }: { runId: string; name: string }) {
  const { t } = useTranslation();
  const api = useApi();
  const id = useId();
  const [filter, setFilter] = useState<Filter>("wrong");
  const [difficulty, setDifficulty] = useState<string>("all");
  const detail = useQuery({ queryKey: ["benchmark-run", runId], queryFn: () => endpoints.benchmarkRun(api, runId), staleTime: Infinity });
  const rows = useMemo(
    () =>
      (detail.data?.results ?? []).filter(
        (r) => (filter === "all" || !r.correct) && (difficulty === "all" || r.difficulty === difficulty),
      ),
    [detail.data, filter, difficulty],
  );

  return (
    <section aria-labelledby={`${id}-title`} className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id={`${id}-title`} className="text-h3 text-fg">
          {t("benchmark.questionsOf", { name })}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div role="radiogroup" aria-label={t("benchmark.filter")} className="flex rounded-md border border-line-strong p-0.5">
            {(["wrong", "all"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={filter === value}
                onClick={() => {
                  setFilter(value);
                }}
                className={cn(
                  "rounded-sm px-2.5 py-1 text-small transition-colors",
                  filter === value ? "bg-accent-soft text-accent" : "text-fg-secondary hover:text-fg",
                )}
              >
                {t(`benchmark.filters.${value}`)}
              </button>
            ))}
          </div>
          <label htmlFor={`${id}-difficulty`} className="sr-only">
            {t("benchmark.difficultyLabel")}
          </label>
          <select
            id={`${id}-difficulty`}
            value={difficulty}
            className={SELECT}
            onChange={(e) => {
              setDifficulty(e.target.value);
            }}
          >
            <option value="all">{t("benchmark.allDifficulties")}</option>
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>
                {t(`benchmark.difficulty.${d}`)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {detail.isPending ? (
        <Skeleton className="h-64" />
      ) : detail.isError ? (
        <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong px-4 py-8 text-center text-fg-secondary">{t("benchmark.noRows")}</p>
      ) : (
        <ul className="min-w-0 rounded-lg border border-line bg-surface-1">
          {rows.map((result) => (
            <Row key={result.item_id} result={result} />
          ))}
        </ul>
      )}
    </section>
  );
}
