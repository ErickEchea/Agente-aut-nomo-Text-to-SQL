import { describe, expect, it } from "vitest";

import type { ChartSpec } from "../../api/types";
import { buildChartOption, isChartable, type ChartTokens } from "./chart-option";

const tokens: ChartTokens = {
  palette: ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"],
  fg: "fg",
  fgSecondary: "fg2",
  fgMuted: "fg3",
  line: "line",
  lineStrong: "line2",
  surface1: "s1",
  surface2: "s2",
  fontSans: "sans",
  fontMono: "mono",
};

function bar(labels: string[]): ChartSpec {
  return {
    kind: "bar",
    step: 0,
    candidates: ["bar", "table"],
    reason: "ranking",
    kpis: [],
    option: {
      title: { text: "Top" },
      tooltip: { trigger: "axis" },
      legend: null,
      xAxis: { type: "category", name: "producto", data: labels },
      yAxis: { type: "value", name: "ingresos", data: null },
      series: [{ type: "bar", name: "ingresos", data: labels.map((_, i) => 100 * (i + 1)), stack: null }],
    },
  };
}

type Loose = Record<string, unknown> & { series: Record<string, unknown>[] };

describe("buildChartOption", () => {
  it("applies the mark specs: ≤24 px bars, rounded data ends, single series without legend", () => {
    const option = buildChartOption(bar(["A", "B"]), tokens, "en", { animate: false }) as unknown as Loose;
    const series = option.series[0];
    expect(series?.["barMaxWidth"]).toBe(24);
    expect((series?.["itemStyle"] as { borderRadius: number[] }).borderRadius).toEqual([4, 4, 0, 0]);
    expect((option["legend"] as { show: boolean }).show).toBe(false);
    expect(option["color"]).toEqual(tokens.palette);
    expect(option["animation"]).toBe(false);
  });

  it("turns long category labels into a horizontal bar chart, top item first", () => {
    const option = buildChartOption(
      bar(["Pollo entero por kg Mr. Pollo", "Leche entera 1 L Parmalat"]),
      tokens,
      "es",
      { animate: true },
    ) as unknown as Loose;
    const yAxis = option["yAxis"] as { type: string; inverse: boolean };
    expect(yAxis.type).toBe("category");
    expect(yAxis.inverse).toBe(true);
    expect((option.series[0]?.["itemStyle"] as { borderRadius: number[] }).borderRadius).toEqual([0, 4, 4, 0]);
  });

  it("adapts to narrow containers", () => {
    const option = buildChartOption(
      bar(["Pollo entero por kg Mr. Pollo", "Leche entera 1 L Parmalat"]),
      tokens,
      "es",
      { animate: false, width: 320 },
    ) as unknown as Loose;
    expect((option["xAxis"] as { splitNumber: number }).splitNumber).toBe(3);
    expect((option["yAxis"] as { axisLabel: { width: number } }).axisLabel.width).toBe(109);
  });

  it("formats money tooltips in USD", () => {
    const option = buildChartOption(bar(["A"]), tokens, "en", { animate: false }) as unknown as Loose;
    const format = (option["tooltip"] as { valueFormatter: (v: unknown) => string }).valueFormatter;
    expect(format(1234.5)).toBe("$1,234.50");
  });

  it("does not chart KPI or table specs", () => {
    const kpi: ChartSpec = { kind: "kpi", step: 0, candidates: ["kpi"], reason: "", option: null, kpis: [{ label: "x", value: 1 }] };
    expect(buildChartOption(kpi, tokens, "es", { animate: false })).toBeNull();
    expect(isChartable(kpi)).toBe(false);
    expect(isChartable(bar(["A"]))).toBe(true);
    expect(isChartable(null)).toBe(false);
  });
});
