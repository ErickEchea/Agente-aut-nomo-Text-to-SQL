/** Accuracy vs p95 latency: one point per configuration, with the selection band (ADR-0003 §4). */
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { BenchmarkRunOut } from "../../api/types";
import { usePreferences } from "../../app/preferences";
import { formatNumber } from "../../lib/format";
import { accuracyScale, latencyScale, project } from "./model";

const W = 640;
const H = 300;
const PAD = { left: 52, right: 24, top: 18, bottom: 44 };

interface Props {
  runs: BenchmarkRunOut[];
  colors: Map<string, string>;
  selected: string | null;
  margin: number; // selection margin as a fraction (0.02 = 2 points)
}

export function TradeoffChart({ runs, colors, selected, margin }: Props) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const titleId = useId();
  const [focus, setFocus] = useState<string | null>(null);
  const points = runs.map((run) => ({
    name: run.config.name,
    seconds: run.summary.latency_p95_ms / 1000,
    accuracy: run.summary.accuracy * 100,
    eligible: run.eligible,
  }));
  const x = latencyScale(points.map((p) => p.seconds));
  // The band hangs from the best *eligible* configuration: that is where the rule looks.
  const pool = points.some((p) => p.eligible) ? points.filter((p) => p.eligible) : points;
  const best = Math.max(...pool.map((p) => p.accuracy));
  const y = accuracyScale(points.map((p) => p.accuracy), margin * 100);
  const px = (v: number) => project(v, x, PAD.left, W - PAD.right);
  const py = (v: number) => project(v, y, H - PAD.bottom, PAD.top);
  const bandTop = py(best);
  const bandBottom = py(Math.max(y.min, best - margin * 100));
  const active = points.find((p) => p.name === focus) ?? null;

  return (
    <figure className="grid min-w-0 gap-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-labelledby={titleId}
        className="h-auto w-full overflow-visible"
        onMouseLeave={() => {
          setFocus(null);
        }}
      >
        <title id={titleId}>{t("benchmark.tradeoffTitle")}</title>
        <rect
          x={PAD.left}
          y={bandTop}
          width={W - PAD.left - PAD.right}
          height={Math.max(2, bandBottom - bandTop)}
          style={{ fill: "var(--accent-soft)" }}
        />
        <text x={W - PAD.right - 4} y={bandTop - 4} textAnchor="end" className="fill-[var(--fg-muted)] text-[11px]">
          {t("benchmark.band", { margin: margin * 100 })}
        </text>
        {y.ticks.map((tick) => (
          <g key={`y${tick}`}>
            <line x1={PAD.left} x2={W - PAD.right} y1={py(tick)} y2={py(tick)} style={{ stroke: "var(--line)" }} strokeWidth={1} />
            <text x={PAD.left - 8} y={py(tick) + 4} textAnchor="end" className="fill-[var(--fg-muted)] font-mono text-[11px]">
              {tick}
            </text>
          </g>
        ))}
        {x.ticks.map((tick) => (
          <text key={`x${tick}`} x={px(tick)} y={H - PAD.bottom + 18} textAnchor="middle" className="fill-[var(--fg-muted)] font-mono text-[11px]">
            {formatNumber(tick, locale)}
          </text>
        ))}
        <text x={(PAD.left + W - PAD.right) / 2} y={H - 6} textAnchor="middle" className="fill-[var(--fg-secondary)] text-[12px]">
          {t("benchmark.axisLatency")}
        </text>
        <text
          transform={`translate(14 ${(PAD.top + H - PAD.bottom) / 2}) rotate(-90)`}
          textAnchor="middle"
          className="fill-[var(--fg-secondary)] text-[12px]"
        >
          {t("benchmark.axisAccuracy")}
        </text>
        {points.map((point) => {
          const cx = px(point.seconds);
          const cy = py(point.accuracy);
          const chosen = point.name === selected;
          return (
            <g
              key={point.name}
              tabIndex={0}
              role="img"
              aria-label={`${t("benchmark.pointLabel", {
                name: point.name,
                accuracy: formatNumber(point.accuracy / 100, locale, "percent"),
                seconds: formatNumber(point.seconds, locale),
              })}${point.eligible ? "" : `. ${t("benchmark.notEligible")}`}`}
              className="cursor-default outline-none [&:focus-visible>circle:first-child]:stroke-[var(--accent)]"
              onMouseEnter={() => {
                setFocus(point.name);
              }}
              onFocus={() => {
                setFocus(point.name);
              }}
              onBlur={() => {
                setFocus(null);
              }}
            >
              <circle cx={cx} cy={cy} r={16} style={{ fill: "transparent", stroke: "transparent" }} strokeWidth={2} />
              {chosen ? <circle cx={cx} cy={cy} r={11} style={{ fill: "none", stroke: colors.get(point.name) }} strokeWidth={2} /> : null}
              {point.eligible ? (
                <circle cx={cx} cy={cy} r={6} style={{ fill: colors.get(point.name), stroke: "var(--surface-1)" }} strokeWidth={2} />
              ) : (
                <circle cx={cx} cy={cy} r={5} style={{ fill: "var(--surface-1)", stroke: colors.get(point.name) }} strokeWidth={2} />
              )}
              {chosen ? (
                <text x={cx} y={cy - 16} textAnchor="middle" className="fill-[var(--fg)] text-[12px] font-medium">
                  {t("benchmark.chosen")}
                </text>
              ) : null}
            </g>
          );
        })}
        {active ? (
          <g pointerEvents="none">
            <rect
              x={Math.min(px(active.seconds) + 12, W - PAD.right - 190)}
              y={Math.max(PAD.top, py(active.accuracy) - 52)}
              width={186}
              height={46}
              rx={6}
              style={{ fill: "var(--surface-3)", stroke: "var(--line-strong)" }}
            />
            <text x={Math.min(px(active.seconds) + 22, W - PAD.right - 180)} y={Math.max(PAD.top, py(active.accuracy) - 52) + 19} className="fill-[var(--fg)] text-[12px] font-medium">
              {active.name}
            </text>
            <text x={Math.min(px(active.seconds) + 22, W - PAD.right - 180)} y={Math.max(PAD.top, py(active.accuracy) - 52) + 36} className="fill-[var(--fg-secondary)] font-mono text-[11px]">
              {t("benchmark.tooltip", {
                accuracy: formatNumber(active.accuracy / 100, locale, "percent"),
                seconds: formatNumber(active.seconds, locale),
              })}
            </text>
          </g>
        ) : null}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1.5 text-small text-fg-secondary">
        {points.map((point) => (
          <span key={point.name} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="size-2.5 rounded-full border-2"
              style={{ borderColor: colors.get(point.name), background: point.eligible ? colors.get(point.name) : "transparent" }}
            />
            {point.name}
          </span>
        ))}
        {points.some((p) => !p.eligible) ? <span className="text-fg-muted">{t("benchmark.hollowLegend")}</span> : null}
      </figcaption>
    </figure>
  );
}
