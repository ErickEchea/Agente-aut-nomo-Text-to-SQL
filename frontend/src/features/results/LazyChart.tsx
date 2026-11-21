import { lazy, Suspense, type ComponentProps } from "react";

import { Skeleton } from "../../components/ui/primitives";

// ECharts is the largest dependency: load it only when a chart is actually shown.
const ChartView = lazy(() => import("./ChartView").then((module) => ({ default: module.ChartView })));

export function LazyChartView(props: ComponentProps<typeof ChartView>) {
  return (
    <Suspense fallback={<Skeleton className="w-full" style={{ height: (props.height ?? 320) + 32 }} />}>
      <ChartView {...props} />
    </Suspense>
  );
}
