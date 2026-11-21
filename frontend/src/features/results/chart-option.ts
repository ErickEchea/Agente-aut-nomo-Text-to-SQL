/**
 * Turns the backend's validated chart spec into a themed ECharts option.
 * Mark specs follow the dataviz method: bars ≤ 24 px with 4 px rounded data ends, 2 px lines,
 * 8 px markers with a surface ring, hairline solid gridlines, text in text tokens (never series
 * colors), a legend only for two or more series, and tooltips on every mark.
 */
import type { EChartsCoreOption } from "echarts/core";

import type { ChartSpec } from "../../api/types";
import { formatCompact, formatNumber, kindForColumn, type ValueKind } from "../../lib/format";

export interface ChartTokens {
  palette: string[];
  fg: string;
  fgSecondary: string;
  fgMuted: string;
  line: string;
  lineStrong: string;
  surface1: string;
  surface2: string;
  fontSans: string;
  fontMono: string;
}

const LONG_LABEL = 12;

export function readChartTokens(element: Element = document.documentElement): ChartTokens {
  const style = getComputedStyle(element);
  const v = (name: string) => style.getPropertyValue(name).trim();
  return {
    palette: Array.from({ length: 8 }, (_, i) => v(`--data-${i + 1}`)),
    fg: v("--fg"),
    fgSecondary: v("--fg-secondary"),
    fgMuted: v("--fg-muted"),
    line: v("--line"),
    lineStrong: v("--line-strong"),
    surface1: v("--surface-1"),
    surface2: v("--surface-2"),
    fontSans: v("--nx-font-sans"),
    fontMono: v("--nx-font-mono"),
  };
}

function valueKind(spec: ChartSpec): ValueKind {
  const option = spec.option;
  const name = option?.series[0]?.name ?? option?.yAxis?.name ?? "";
  return kindForColumn(name, []);
}

function numeric(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (Array.isArray(value)) return numeric(value.at(-1));
  if (value && typeof value === "object" && "value" in value) return numeric(value.value);
  return null;
}

export function buildChartOption(
  spec: ChartSpec,
  tokens: ChartTokens,
  locale: string,
  { animate, width = 800 }: { animate: boolean; width?: number },
): EChartsCoreOption | null {
  const narrow = width < 480;
  const source = spec.option;
  if (!source || spec.kind === "kpi" || spec.kind === "table") return null;

  const kind = valueKind(spec);
  const axisFormat = (value: number) => formatCompact(value, locale, kind);
  const tooltipFormat = (value: unknown) => {
    const n = numeric(value);
    return n === null ? String(value) : formatNumber(n, locale, kind);
  };
  const multi = source.series.length > 1;

  const text = { color: tokens.fgSecondary, fontFamily: tokens.fontSans, fontSize: 12 };
  const base = {
    animation: animate,
    animationDuration: animate ? 360 : 0,
    color: tokens.palette,
    backgroundColor: "transparent",
    textStyle: text,
    aria: { enabled: true },
    tooltip: {
      trigger: source.tooltip["trigger"] === "item" ? "item" : "axis",
      backgroundColor: tokens.surface2,
      borderColor: tokens.lineStrong,
      borderWidth: 1,
      padding: [6, 10],
      textStyle: { color: tokens.fg, fontFamily: tokens.fontSans, fontSize: 12 },
      valueFormatter: tooltipFormat,
      axisPointer: { type: "shadow", shadowStyle: { color: tokens.line, opacity: 0.35 } },
      confine: true,
    },
    legend: multi
      ? { show: true, top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: text }
      : { show: false },
  };

  const first = source.series[0];
  if (!first) return null;

  if (first.type === "pie") {
    return {
      ...base,
      tooltip: { ...base.tooltip, trigger: "item", axisPointer: undefined },
      legend: { show: true, bottom: 0, icon: "circle", itemWidth: 8, itemHeight: 8, textStyle: text },
      series: [
        {
          type: "pie",
          name: first.name,
          data: first.data,
          radius: ["0%", "68%"],
          center: ["50%", "45%"],
          itemStyle: { borderColor: tokens.surface1, borderWidth: 2, borderRadius: 4 },
          label: { color: tokens.fgSecondary, fontFamily: tokens.fontSans, formatter: "{d}%" },
          labelLine: { lineStyle: { color: tokens.lineStrong } },
          emphasis: { scale: false, itemStyle: { shadowBlur: 0 } },
        },
      ],
    };
  }

  const categoryAxis = source.xAxis?.type === "category" ? source.xAxis : null;
  const labels = categoryAxis?.data ?? [];
  // Long category names (products, branches) read better on a horizontal bar chart.
  const horizontal =
    first.type === "bar" &&
    labels.length > 0 &&
    labels.reduce((sum, label) => sum + label.length, 0) / labels.length > LONG_LABEL;

  const axisLine = { show: true, lineStyle: { color: tokens.lineStrong, width: 1 } };
  const splitLine = { show: true, lineStyle: { color: tokens.line, width: 1, type: "solid" } };
  const nameStyle = { color: tokens.fgMuted, fontFamily: tokens.fontSans, fontSize: 11 };

  const category = {
    type: "category",
    data: labels,
    axisLine,
    axisTick: { show: false },
    axisLabel: {
      color: tokens.fgMuted,
      fontFamily: tokens.fontSans,
      hideOverlap: true,
      ...(horizontal ? { width: Math.min(160, Math.round(width * 0.34)), overflow: "truncate" } : {}),
    },
    inverse: horizontal, // first (top-ranked) category on top
  };
  const value = {
    type: "value",
    name: horizontal ? undefined : source.yAxis?.name,
    nameTextStyle: nameStyle,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine,
    splitNumber: narrow ? 3 : 5,
    axisLabel: { color: tokens.fgMuted, fontFamily: tokens.fontMono, formatter: axisFormat, hideOverlap: true },
  };

  const scatter = first.type === "scatter";
  const xAxis = scatter
    ? { ...value, name: source.xAxis?.name, splitLine }
    : horizontal
      ? value
      : category;
  const yAxis = scatter ? value : horizontal ? category : value;

  const series = source.series.map((s) => {
    if (s.type === "bar") {
      return {
        type: "bar",
        name: s.name,
        data: s.data,
        stack: s.stack ?? undefined,
        barMaxWidth: 24,
        itemStyle: {
          borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
          ...(s.stack ? { borderColor: tokens.surface1, borderWidth: 1 } : {}),
        },
        emphasis: { focus: multi ? "series" : "none" },
      };
    }
    if (s.type === "line") {
      const points = Array.isArray(s.data) ? s.data.length : 0;
      return {
        type: "line",
        name: s.name,
        data: s.data,
        lineStyle: { width: 2, cap: "round", join: "round" },
        symbol: "circle",
        symbolSize: 8,
        showSymbol: points <= 24,
        itemStyle: { borderColor: tokens.surface1, borderWidth: 2 },
        ...(multi ? {} : { areaStyle: { opacity: 0.1 } }),
      };
    }
    return {
      type: "scatter",
      name: s.name,
      data: s.data,
      symbolSize: 9,
      itemStyle: { borderColor: tokens.surface1, borderWidth: 2 },
    };
  });

  return {
    ...base,
    tooltip: {
      ...base.tooltip,
      ...(scatter ? { trigger: "item", axisPointer: undefined } : {}),
      ...(first.type === "line" ? { axisPointer: { type: "line", lineStyle: { color: tokens.lineStrong } } } : {}),
    },
    grid: { left: 8, right: 16, top: multi ? 36 : 28, bottom: 8, containLabel: true },
    xAxis,
    yAxis,
    series,
  };
}

/** A spec that renders as an ECharts chart (KPI and table specs are shown by other components). */
export function isChartable(chart: ChartSpec | null | undefined): boolean {
  return chart !== undefined && chart !== null && chart.kind !== "table" && chart.kind !== "kpi" && chart.option !== null;
}
