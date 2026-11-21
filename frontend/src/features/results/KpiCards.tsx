import { useTranslation } from "react-i18next";

import type { Kpi } from "../../api/types";
import { usePreferences } from "../../app/preferences";
import { cn } from "../../lib/cn";
import { formatCompact, formatNumber, kindForColumn } from "../../lib/format";

export type KpiItem = Kpi & { caption?: string | undefined };

/** KPI cards with hierarchy: the first figure is the hero, the rest are compact. */
export function KpiCards({ kpis, className }: { kpis: KpiItem[]; className?: string }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  if (kpis.length === 0) return null;
  const [hero, ...rest] = kpis;
  if (!hero) return null;
  const heroKind = kindForColumn(hero.label, [hero.value]);
  return (
    <section aria-label={t("results.kpis")} className={cn("grid gap-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]", className)}>
      <div className="relative overflow-hidden rounded-lg border border-accent/30 bg-surface-1 p-4">
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-0.5 bg-accent" />
        <p className="label-micro">{hero.label}</p>
        <p className="figures mt-1 text-[2rem] leading-10 font-semibold text-fg sm:text-[2.5rem] sm:leading-[3rem]" title={formatNumber(hero.value, locale, heroKind)}>
          {formatNumber(hero.value, locale, heroKind)}
        </p>
        {hero.caption ? <p className="mt-1 truncate text-fg-secondary">{hero.caption}</p> : null}
      </div>
      {rest.length > 0 ? (
        <ul className="grid content-start gap-2">
          {rest.map((kpi) => {
            const kind = kindForColumn(kpi.label, [kpi.value]);
            return (
              <li key={kpi.label} className="flex items-baseline justify-between gap-3 rounded-md border border-line bg-surface-1 px-3 py-2">
                <span className="min-w-0 truncate text-small text-fg-secondary">
                  {kpi.label}
                  {kpi.caption ? <span className="text-fg-muted"> · {kpi.caption}</span> : null}
                </span>
                <span className="figures text-h3 font-medium text-fg" title={formatNumber(kpi.value, locale, kind)}>
                  {formatCompact(kpi.value, locale, kind)}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
