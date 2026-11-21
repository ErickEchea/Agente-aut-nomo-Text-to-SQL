import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { ImageDown } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ChartSpec } from "../../api/types";
import { usePreferences } from "../../app/preferences";
import { Button } from "../../components/ui/button";
import { downloadDataUrl, safeFilename } from "../../lib/csv";
import { buildChartOption, readChartTokens } from "./chart-option";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  CanvasRenderer,
]);

interface ChartViewProps {
  spec: ChartSpec;
  title: string;
  height?: number;
  exportable?: boolean;
}

export function ChartView({ spec, title, height = 320, exportable = true }: ChartViewProps) {
  const { t } = useTranslation();
  const { resolvedTheme, locale } = usePreferences();
  const reduced = useReducedMotion() ?? false;
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  // Width bucket (not raw pixels) so resizing does not rebuild the option on every frame.
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const instance = echarts.init(element, null, { renderer: "canvas" });
    chart.current = instance;
    const observer = new ResizeObserver(() => {
      instance.resize();
      setNarrow(element.clientWidth < 480);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const option = buildChartOption(spec, readChartTokens(), locale, {
      animate: !reduced,
      width: chart.current?.getWidth() ?? (narrow ? 320 : 800),
    });
    if (option) chart.current?.setOption(option, { notMerge: true });
    // resolvedTheme is a dependency on purpose: tokens are re-read after a theme switch.
  }, [spec, locale, reduced, resolvedTheme, narrow]);

  const exportPng = () => {
    const instance = chart.current;
    if (!instance) return;
    const url = instance.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: readChartTokens().surface1,
    });
    downloadDataUrl(url, safeFilename(title, "png"));
  };

  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <figcaption className="text-small text-fg-secondary">{spec.reason ? t("results.chartReason", { reason: spec.reason }) : null}</figcaption>
        {exportable ? (
          <Button variant="ghost" size="sm" onClick={exportPng}>
            <ImageDown />
            {t("results.exportPng")}
          </Button>
        ) : null}
      </div>
      <div ref={host} role="img" aria-label={title} style={{ height }} className="w-full" />
    </figure>
  );
}
