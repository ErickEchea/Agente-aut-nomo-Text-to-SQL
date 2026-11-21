/** EXPLAIN-based analysis: plan, findings and index suggestions with cost before/after. */
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Gauge, Info, ListTree, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import type { FindingOut, OptimizationOut, SuggestionOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState } from "../../components/Page";
import { Button } from "../../components/ui/button";
import { Badge, Spinner } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { formatNumber } from "../../lib/format";
import { CopyButton } from "./SqlBlock";

const ENGINE_LABEL: Record<string, string> = { postgresql: "PostgreSQL", mysql: "MySQL", sqlite: "SQLite" };

function FindingRow({ finding }: { finding: FindingOut }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const rows = finding.rows ? t("results.rowsSuffix", { rows: formatNumber(finding.rows, locale, "integer") }) : "";
  const Icon = finding.severity === "high" ? AlertTriangle : finding.code === "no_issue" ? CheckCircle2 : Info;
  return (
    <li className="flex items-start gap-2 text-small">
      <Icon
        aria-hidden="true"
        className={cn(
          "mt-0.5 size-4 shrink-0",
          finding.severity === "high" ? "text-warning" : finding.code === "no_issue" ? "text-success" : "text-info",
        )}
      />
      <span className="text-fg-secondary">
        {t(`results.finding.${finding.code}`, {
          table: finding.table ?? "",
          rows,
          columns: finding.columns.join(", "),
        })}
      </span>
    </li>
  );
}

function CostBars({ suggestion }: { suggestion: SuggestionOut }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const before = suggestion.cost_before ?? 0;
  const after = suggestion.cost_after ?? 0;
  const pct = Math.round((suggestion.improvement ?? 0) * 100);
  const bar = (label: string, value: number, tone: string): ReactNode => (
    <div className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-2">
      <span className="text-small text-fg-muted">{label}</span>
      <span className="h-2 rounded-full bg-surface-3">
        <span className={cn("block h-full rounded-full", tone)} style={{ width: `${before > 0 ? Math.max(2, (value / before) * 100) : 0}%` }} />
      </span>
      <span className="figures text-small text-fg">{formatNumber(value, locale)}</span>
    </div>
  );
  return (
    <div className="grid gap-1.5" aria-label={t("results.improvement", { pct })}>
      {bar(t("results.before"), before, "bg-fg-muted")}
      {bar(t("results.after"), after, "bg-success")}
      <p className="text-small font-medium text-success">{t("results.improvement", { pct })}</p>
    </div>
  );
}

function Report({ report }: { report: OptimizationOut }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const engine = ENGINE_LABEL[report.engine] ?? report.engine;
  return (
    <div className="grid min-w-0 grid-cols-1 gap-5">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        {report.supports_costs && report.total_cost !== null ? (
          <p>
            <span className="label-micro mr-2">{t("results.totalCost")}</span>
            <span className="figures text-h2 text-fg">{formatNumber(report.total_cost, locale)}</span>
          </p>
        ) : (
          <p className="text-small text-fg-muted">{t("results.noCosts", { engine })}</p>
        )}
        <Badge tone="info">{engine}</Badge>
      </div>

      <section className="grid gap-2">
        <h4 className="label-micro">{t("results.findings")}</h4>
        <ul className="grid gap-1.5">
          {report.findings.map((finding, i) => (
            <FindingRow key={i} finding={finding} />
          ))}
        </ul>
      </section>

      {report.suggestions.length > 0 ? (
        <section className="grid gap-3">
          <h4 className="label-micro">{t("results.suggestions")}</h4>
          {report.suggestions.map((s) => (
            <article key={s.ddl} className="grid min-w-0 gap-3 rounded-lg border border-success/30 bg-success-soft/30 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-2 font-medium text-fg">
                  <Sparkles aria-hidden="true" className="size-4 text-success" />
                  {s.table} ({s.columns.join(", ")})
                  <Badge>{t(`results.reasons.${s.reason}`)}</Badge>
                </p>
                <CopyButton text={s.ddl} label={t("results.copyDdl")} />
              </div>
              <code tabIndex={0} className="min-w-0 overflow-x-auto rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-small whitespace-nowrap text-fg">
                {s.ddl}
              </code>
              {s.cost_before !== null && s.cost_after !== null ? (
                <>
                  <CostBars suggestion={s} />
                  <p className="text-micro text-fg-muted">{t("results.hypothetical")}</p>
                </>
              ) : (
                <p className="text-micro text-fg-muted">{t("results.notMeasured")}</p>
              )}
            </article>
          ))}
          <p className="text-small text-fg-muted">{t("results.readOnlyNote")}</p>
        </section>
      ) : null}

      <details className="group rounded-md border border-line">
        <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-small text-fg-secondary select-none">
          <ListTree aria-hidden="true" className="size-4" />
          {t("results.plan")}
        </summary>
        <ol className="grid gap-0.5 border-t border-line px-3 py-2 font-mono text-[0.75rem]">
          {report.plan.map((step, i) => (
            <li key={i} className="flex min-w-0 flex-wrap items-baseline gap-x-2" style={{ paddingLeft: `${step.depth * 1}rem` }}>
              <span className="text-accent">{step.operation}</span>
              {step.table ? <span className="text-fg">{step.table}</span> : null}
              {step.rows !== null ? <span className="text-fg-muted">{t("results.rowsSuffix", { rows: formatNumber(step.rows, locale, "integer") })}</span> : null}
              {step.detail ? <span className="min-w-0 truncate text-fg-muted">{step.detail}</span> : null}
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

export function OptimizationPanel({ runId, step }: { runId: string; step: number }) {
  const { t } = useTranslation();
  const api = useApi();
  const analysis = useMutation({ mutationFn: () => endpoints.optimizeStep(api, runId, step) });
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid max-w-2xl gap-1">
          <p className="flex items-center gap-2 font-medium text-fg">
            <Gauge aria-hidden="true" className="size-4 text-accent" />
            {t("results.optimizationTitle")}
          </p>
          <p className="text-small text-fg-muted">{t("results.optimizationIntro")}</p>
        </div>
        <Button
          variant={analysis.data ? "secondary" : "primary"}
          size="sm"
          disabled={analysis.isPending}
          onClick={() => {
            analysis.mutate();
          }}
        >
          {analysis.isPending ? <Spinner /> : <Gauge />}
          {analysis.isPending ? t("results.analyzing") : analysis.data ? t("results.reanalyze") : t("results.analyze")}
        </Button>
      </div>
      {analysis.isError ? <ErrorState error={analysis.error} onRetry={() => { analysis.mutate(); }} /> : null}
      {analysis.data ? <Report report={analysis.data} /> : null}
    </div>
  );
}
