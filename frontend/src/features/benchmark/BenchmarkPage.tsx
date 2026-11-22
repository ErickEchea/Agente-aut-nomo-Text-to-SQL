/** Golden-set benchmark results: the data-driven default model, the trade-off, every metric and question. */
import { useQuery } from "@tanstack/react-query";
import { Award, CircleCheck, Gauge, Hourglass, ShieldCheck, Wrench } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import type { BenchmarkOverview, BenchmarkRunOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState, Page, PageHeader } from "../../components/Page";
import { Badge, Panel, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { formatDate, formatDuration, formatNumber } from "../../lib/format";
import { CopyButton } from "../results/SqlBlock";
import { DIFFICULTIES, isRouted, modelsOf, seriesColors } from "./model";
import { QuestionResults } from "./QuestionResults";
import { TradeoffChart } from "./TradeoffChart";

const COMMAND = "make bench";

function pct(value: number | null | undefined, locale: string): string {
  return value === null || value === undefined ? "–" : formatNumber(value, locale, "percent");
}

function EmptyBenchmark() {
  const { t } = useTranslation();
  const metrics = [
    { icon: CircleCheck, key: "accuracy" },
    { icon: Hourglass, key: "latency" },
    { icon: Wrench, key: "repairs" },
    { icon: ShieldCheck, key: "grounding" },
  ] as const;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Panel className="flex flex-col items-start gap-4 p-6">
        <span className="flex size-11 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-fg-muted">
          <Gauge aria-hidden="true" className="size-5" />
        </span>
        <h2 className="font-display text-h2 text-fg">{t("benchmark.emptyTitle")}</h2>
        <p className="max-w-xl text-fg-secondary">{t("benchmark.emptyBody")}</p>
        <div className="grid w-full gap-2">
          <p className="label-micro">{t("benchmark.howTo")}</p>
          <div className="flex items-center gap-2 rounded-md border border-line bg-surface-2 py-1 pr-1 pl-3">
            <code className="min-w-0 flex-1 overflow-x-auto font-mono text-small whitespace-nowrap text-fg">{COMMAND}</code>
            <CopyButton text={COMMAND} />
          </div>
        </div>
      </Panel>
      <Panel className="p-6">
        <h2 className="mb-4 text-h3 text-fg">{t("benchmark.measures")}</h2>
        <ul className="grid gap-3">
          {metrics.map(({ icon: Icon, key }) => (
            <li key={key} className="flex items-start gap-3 text-fg-secondary">
              <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent" />
              {t(`benchmark.metrics.${key}`)}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function SelectedCard({ data, run }: { data: BenchmarkOverview; run: BenchmarkRunOut }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const s = run.summary;
  const serving = data.serving.model;
  const matches = run.config.model === serving && Object.keys(run.config.nodes ?? {}).length === Object.keys(data.serving.nodes).length;
  return (
    <Panel className="grid gap-5 p-6 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="grid content-start gap-3">
        <p className="flex items-center gap-2 label-micro">
          <Award aria-hidden="true" className="size-4 text-accent" />
          {t("benchmark.selectedTitle")}
        </p>
        <h2 className="font-display text-h1 break-words text-fg">{run.config.name}</h2>
        <p className="flex flex-wrap gap-1.5">
          {modelsOf(run).map((model) => (
            <Badge key={model} tone="accent">
              {model}
            </Badge>
          ))}
          {run.config.think === false ? <Badge>{t("benchmark.thinkOff")}</Badge> : null}
        </p>
        <p className="max-w-xl text-small text-fg-secondary">{t("benchmark.rule", { margin: data.selection_margin * 100 })}</p>
        <p className={cn("text-small", matches ? "text-success" : "text-warning")}>
          {matches ? t("benchmark.servingMatches", { model: serving }) : t("benchmark.servingDiffers", { model: serving })}
        </p>
      </div>
      <dl className="grid grid-cols-2 content-start gap-4">
        <div className="col-span-2">
          <dt className="label-micro">{t("benchmark.accuracy")}</dt>
          <dd className="figures font-display text-[3rem] leading-none text-fg">{pct(s.accuracy, locale)}</dd>
          <dd className="text-small text-fg-muted">{t("benchmark.correctOf", { correct: s.correct, items: s.items })}</dd>
        </div>
        <div>
          <dt className="label-micro">{t("benchmark.p50")}</dt>
          <dd className="figures text-h3 text-fg">{formatDuration(s.latency_p50_ms, locale)}</dd>
        </div>
        <div>
          <dt className="label-micro">{t("benchmark.p95")}</dt>
          <dd className="figures text-h3 text-fg">{formatDuration(s.latency_p95_ms, locale)}</dd>
        </div>
      </dl>
    </Panel>
  );
}

function CompareTable({ runs, colors, selected }: { runs: BenchmarkRunOut[]; colors: Map<string, string>; selected: string | null }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const head = "px-3 py-2 text-left font-medium text-fg-secondary whitespace-nowrap";
  const cell = "px-3 py-2.5 figures whitespace-nowrap text-fg";
  return (
    <Panel className="min-w-0">
      <h2 className="px-4 pt-4 text-h3 text-fg">{t("benchmark.compareTitle")}</h2>
      <div tabIndex={0} role="region" aria-label={t("benchmark.compareTitle")} className="min-w-0 overflow-x-auto p-2">
        <table className="w-full border-collapse text-small">
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className={head}>{t("benchmark.columns.config")}</th>
              <th scope="col" className={head}>{t("benchmark.accuracy")}</th>
              {DIFFICULTIES.map((d) => (
                <th key={d} scope="col" className={head}>{t(`benchmark.difficulty.${d}`)}</th>
              ))}
              <th scope="col" className={head}>{t("benchmark.p50")}</th>
              <th scope="col" className={head}>{t("benchmark.p95")}</th>
              <th scope="col" className={head}>{t("benchmark.columns.firstTry")}</th>
              <th scope="col" className={head}>{t("benchmark.columns.recovery")}</th>
              <th scope="col" className={head}>{t("benchmark.columns.tokens")}</th>
              <th scope="col" className={head}>{t("benchmark.columns.fallback")}</th>
              <th scope="col" className={head}>{t("benchmark.columns.recall")}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const s = run.summary;
              return (
                <tr key={run.id} className={cn("border-b border-line last:border-b-0", run.config.name === selected && "bg-accent-soft/40")}>
                  <th scope="row" className="px-3 py-2.5 text-left font-normal">
                    <span className="flex items-center gap-2">
                      <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full" style={{ background: colors.get(run.config.name) }} />
                      <span className="grid">
                        <span className="font-medium whitespace-nowrap text-fg">{run.config.name}</span>
                        <span className="font-mono text-micro whitespace-nowrap text-fg-muted">
                          {isRouted(run) ? t("benchmark.routed") : modelsOf(run).join(", ")}
                        </span>
                        {run.eligible ? null : (
                          <Badge tone="warning" className="mt-1 w-fit normal-case">
                            {t("benchmark.notEligible")}
                          </Badge>
                        )}
                      </span>
                    </span>
                  </th>
                  <td className={cell}>
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-16 rounded-full bg-surface-3">
                        <span className="block h-full rounded-full" style={{ width: `${s.accuracy * 100}%`, background: colors.get(run.config.name) }} />
                      </span>
                      <span className="font-medium">{pct(s.accuracy, locale)}</span>
                    </span>
                  </td>
                  {DIFFICULTIES.map((d) => (
                    <td key={d} className={cell}>{pct(s.by_difficulty[d]?.accuracy, locale)}</td>
                  ))}
                  <td className={cell}>{formatDuration(s.latency_p50_ms, locale)}</td>
                  <td className={cell}>{formatDuration(s.latency_p95_ms, locale)}</td>
                  <td className={cell}>{pct(s.first_attempt_rate, locale)}</td>
                  <td className={cell}>{pct(s.recovery_rate, locale)}</td>
                  <td className={cell}>{formatNumber(s.tokens_per_question, locale, "integer")}</td>
                  <td className={cell}>{pct(s.grounding_fallback_rate, locale)}</td>
                  <td className={cell}>{pct(s.recall_at_5, locale)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function BenchmarkPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const overview = useQuery({ queryKey: ["benchmark"], queryFn: () => endpoints.benchmarkOverview(api) });
  const [picked, setPicked] = useState<string | null>(null);

  const data = overview.data;
  const runs = data?.runs ?? [];
  const colors = seriesColors(runs.map((r) => r.config.name));
  const selectedRun = runs.find((r) => r.config.name === data?.selected) ?? null;
  const shown = runs.find((r) => r.config.name === picked) ?? selectedRun ?? runs[0] ?? null;
  const newest = runs.reduce<string | null>((acc, r) => (r.finished_at && (!acc || r.finished_at > acc) ? r.finished_at : acc), null);

  return (
    <Page>
      <PageHeader
        title={t("benchmark.title")}
        subtitle={t("benchmark.subtitle")}
        actions={
          runs.length > 0 && newest ? (
            <Badge tone="info">
              {t("benchmark.runMeta", { items: runs[0]?.summary.items ?? 0, dataset: runs[0]?.dataset_version ?? "", date: formatDate(newest, locale) })}
            </Badge>
          ) : null
        }
      />
      {overview.isPending ? (
        <Skeleton className="h-96" />
      ) : overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
      ) : runs.length === 0 || !data ? (
        <EmptyBenchmark />
      ) : (
        <>
          {selectedRun ? <SelectedCard data={data} run={selectedRun} /> : null}
          <Panel className="grid min-w-0 gap-3 p-4 sm:p-6">
            <div className="grid gap-1">
              <h2 className="text-h3 text-fg">{t("benchmark.tradeoffTitle")}</h2>
              <p className="max-w-2xl text-small text-fg-secondary">{t("benchmark.tradeoffHint", { margin: data.selection_margin * 100 })}</p>
            </div>
            <TradeoffChart runs={runs} colors={colors} selected={data.selected} margin={data.selection_margin} />
          </Panel>
          <CompareTable runs={runs} colors={colors} selected={data.selected} />
          {shown ? (
            <div className="grid min-w-0 gap-3">
              <div role="radiogroup" aria-label={t("benchmark.pickRun")} className="flex flex-wrap gap-1.5">
                {runs.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    role="radio"
                    aria-checked={run.id === shown.id}
                    onClick={() => {
                      setPicked(run.config.name);
                    }}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-small transition-colors",
                      run.id === shown.id ? "border-accent/60 bg-accent-soft text-fg" : "border-line text-fg-secondary hover:border-line-strong",
                    )}
                  >
                    <span aria-hidden="true" className="size-2 rounded-full" style={{ background: colors.get(run.config.name) }} />
                    {run.config.name}
                  </button>
                ))}
              </div>
              <QuestionResults key={shown.id} runId={shown.id} name={shown.config.name} />
            </div>
          ) : null}
        </>
      )}
    </Page>
  );
}
