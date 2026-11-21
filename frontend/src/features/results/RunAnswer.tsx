/** A finished run: hero answer, KPI cards and the Tabla/Gráfico/SQL/Explicación/Optimización tabs. */
import { BarChart3, BookOpenText, Code2, Gauge, Info, ShieldCheck, Sheet, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ChartSpec, Preferences, RunOut, RunResult, StepOut } from "../../api/types";
import { usePreferences } from "../../app/preferences";
import { Badge } from "../../components/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/overlays";
import { cn } from "../../lib/cn";
import { formatRange } from "../../lib/format";
import { isChartable } from "./chart-option";
import { LazyChartView } from "./LazyChart";
import { DataTable } from "./DataTable";
import { FeedbackBar } from "./FeedbackBar";
import { KpiCards, type KpiItem } from "./KpiCards";
import { PinDialog } from "./PinDialog";
import { SqlBlock } from "./SqlBlock";

type Tab = "table" | "chart" | "sql" | "explanation" | "optimization";


function Assumptions({ result }: { result: RunResult }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const ranges = result.time_ranges.map((r) => `«${r.expression}» = ${formatRange(r.start, r.end, locale)}`);
  const items = ranges.length > 0 ? ranges : result.assumptions;
  if (items.length === 0) return null;
  return (
    <ul aria-label={t("results.assumptions")} className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item}>
          <Badge tone="warning" className="normal-case tracking-normal">
            <Info aria-hidden="true" />
            {item}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function StepTabs({
  run,
  result,
  step,
  chart,
  preferences,
}: {
  run: RunOut;
  result: RunResult;
  step: StepOut;
  chart: ChartSpec | undefined;
  preferences: Preferences | undefined;
}) {
  const { t } = useTranslation();
  const chartable = isChartable(chart);
  const preferred: Tab = preferences?.show_sql
    ? "sql"
    : preferences?.default_chart === "table" || !chartable
      ? "table"
      : "chart";
  const [tab, setTab] = useState<Tab>(preferred);
  const explanation = result.explanation;
  const failedAttempts = result.attempts.filter((a) => a.step === step.index && a.outcome !== "ok");
  const tabs: { id: Tab; icon: typeof Sheet }[] = [
    { id: "table", icon: Sheet },
    { id: "chart", icon: BarChart3 },
    { id: "sql", icon: Code2 },
    { id: "explanation", icon: BookOpenText },
    { id: "optimization", icon: Gauge },
  ];

  return (
    <Tabs value={tab} onValueChange={(value) => { setTab(value as Tab); }} className="min-w-0 rounded-lg border border-line bg-surface-1">
      <TabsList aria-label={step.question}>
        {tabs.map(({ id, icon: Icon }) => (
          <TabsTrigger key={id} value={id}>
            <Icon aria-hidden="true" />
            {t(`results.tabs.${id}`)}
          </TabsTrigger>
        ))}
      </TabsList>
      <div className="p-4">
        <TabsContent value="table" className="outline-none">
          <DataTable columns={step.columns} rows={step.rows} title={step.question} truncated={step.truncated} />
        </TabsContent>
        <TabsContent value="chart" className="outline-none">
          {chartable && chart ? (
            <LazyChartView spec={chart} title={chart.option?.title["text"] ?? step.question} />
          ) : chart?.kind === "kpi" ? (
            <KpiCards kpis={chart.kpis} />
          ) : (
            <p className="py-8 text-center text-fg-muted">{t("results.noChart")}</p>
          )}
        </TabsContent>
        <TabsContent value="sql" className="grid min-w-0 grid-cols-1 gap-4 outline-none">
          <SqlBlock sql={step.sql} />
          {step.tables.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="label-micro mr-1">{t("results.tablesUsed")}</span>
              {step.tables.map((table) => (
                <Badge key={table}>{table}</Badge>
              ))}
            </div>
          ) : null}
          {failedAttempts.length > 0 ? (
            <div className="grid gap-2">
              <h3 className="label-micro">{t("results.attemptsFailed")}</h3>
              <ul className="grid gap-2">
                {failedAttempts.map((attempt) => (
                  <li key={`${attempt.step}-${attempt.attempt}`} className="grid gap-1.5 rounded-md border border-danger/30 bg-danger-soft/40 p-3">
                    <span className="flex flex-wrap items-center gap-2 text-small">
                      <Badge tone="danger">{t("timeline.attempt", { n: attempt.attempt })}</Badge>
                      <span className="text-fg-secondary">
                        <span className="font-mono">{attempt.error?.code}</span> · {attempt.error?.message}
                      </span>
                    </span>
                    {attempt.sql ? <SqlBlock sql={attempt.sql} compact copyable={false} /> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </TabsContent>
        <TabsContent value="explanation" className="grid grid-cols-1 gap-4 outline-none">
          {explanation ? (
            <>
              <p className="text-h3 text-fg">{explanation.headline}</p>
              {explanation.bullets.length > 0 ? (
                <ul className="grid list-disc gap-1 pl-5 text-fg-secondary">
                  {explanation.bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              ) : null}
              {explanation.caveats.length > 0 ? (
                <div className="grid gap-1">
                  <h3 className="label-micro">{t("results.caveats")}</h3>
                  <ul className="grid list-disc gap-1 pl-5 text-small text-fg-secondary">
                    {explanation.caveats.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-fg-secondary">{result.answer}</p>
          )}
          {step.rationale ? <p className="text-small text-fg-muted">{step.rationale}</p> : null}
          {step.warnings.length > 0 ? (
            <ul className="grid gap-1">
              {step.warnings.map((w) => (
                <li key={w} className="flex items-start gap-2 text-small text-warning">
                  <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="figures text-micro text-fg-muted">
            {t("results.tokens", { prompt: run.prompt_tokens, completion: run.completion_tokens, calls: result.tokens.calls })}
          </p>
        </TabsContent>
        <TabsContent value="optimization" className="outline-none">
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <Gauge aria-hidden="true" className="size-6 text-fg-muted" />
            <p className="font-medium text-fg">{t("results.optimizationTitle")}</p>
            <p className="max-w-md text-small text-fg-muted">{t("results.optimizationSoon")}</p>
            <Badge tone="info">{t("common.phase", { n: 5 })}</Badge>
          </div>
        </TabsContent>
      </div>
    </Tabs>
  );
}

export function RunAnswer({ run, preferences }: { run: RunOut; preferences: Preferences | undefined }) {
  const { t } = useTranslation();
  const result = run.result;
  const [stepIndex, setStepIndex] = useState(0);
  if (!result) return null;
  const step = result.results.find((s) => s.index === stepIndex) ?? result.results[0];
  const charts = result.charts;
  // A single-row KPI step names what the figure belongs to (e.g. the branch) with its text column.
  const kpis: KpiItem[] = charts
    .filter((c) => c.kind === "kpi")
    .flatMap((c) => {
      const row = result.results.find((s) => s.index === c.step)?.rows[0];
      const caption = row?.find((v): v is string => typeof v === "string");
      return c.kpis.map((k) => ({ ...k, caption }));
    });
  const explanation = result.explanation;
  const headline = explanation?.headline ?? result.answer;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-3">
        <p className="font-display text-h2 text-fg text-pretty sm:text-[1.375rem] sm:leading-8">{headline}</p>
        <div className="flex flex-wrap items-center gap-2">
          {explanation ? (
            <Badge tone={explanation.fallback ? "warning" : "success"} className="normal-case tracking-normal">
              <ShieldCheck aria-hidden="true" />
              {explanation.fallback ? t("timeline.out.fallback") : t("results.verified")}
            </Badge>
          ) : null}
          <Assumptions result={result} />
        </div>
        {explanation?.fallback ? <p className="text-small text-fg-muted">{t("results.fallback")}</p> : null}
        {explanation && explanation.bullets.length > 0 ? (
          <ul className="grid list-disc gap-1 pl-5 text-fg-secondary marker:text-accent">
            {explanation.bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <KpiCards kpis={kpis} />

      {result.results.length > 1 ? (
        <div role="tablist" aria-label={t("results.steps")} className="flex flex-wrap gap-1">
          {result.results.map((s) => (
            <button
              key={s.index}
              type="button"
              role="tab"
              aria-selected={s.index === step?.index}
              onClick={() => {
                setStepIndex(s.index);
              }}
              className={cn(
                "max-w-full truncate rounded-md border px-3 py-1.5 text-left text-small",
                s.index === step?.index
                  ? "border-accent/50 bg-accent-soft text-fg"
                  : "border-line bg-surface-1 text-fg-secondary hover:bg-surface-3",
              )}
            >
              <span className="label-micro mr-2">{t("results.step", { n: s.index + 1 })}</span>
              {s.question}
            </button>
          ))}
        </div>
      ) : null}

      {step ? (
        <StepTabs
          key={step.index}
          run={run}
          result={result}
          step={step}
          chart={charts.find((c) => c.step === step.index)}
          preferences={preferences}
        />
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <FeedbackBar runId={run.id} answered={result.status === "answered"} />
        {step ? <PinDialog runId={run.id} step={step.index} defaultTitle={step.question} /> : null}
      </div>
    </div>
  );
}
