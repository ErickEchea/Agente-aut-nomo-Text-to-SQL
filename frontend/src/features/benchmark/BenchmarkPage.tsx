import { CircleCheck, Gauge, Hourglass, ShieldCheck, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Page, PageHeader } from "../../components/Page";
import { Badge, Panel } from "../../components/ui/primitives";
import { CopyButton } from "../results/SqlBlock";

const COMMAND = "make bench MODELS=\"qwen2.5-coder:7b qwen3:8b gemma4:e4b-it-qat\"";

/** Honest empty state: the benchmark lands in Phase 6, and NEXUS never shows invented numbers. */
export function BenchmarkPage() {
  const { t } = useTranslation();
  const metrics = [
    { icon: CircleCheck, key: "accuracy" },
    { icon: Hourglass, key: "latency" },
    { icon: Wrench, key: "repairs" },
    { icon: ShieldCheck, key: "grounding" },
  ] as const;
  return (
    <Page>
      <PageHeader title={t("benchmark.title")} subtitle={t("benchmark.subtitle")} actions={<Badge tone="info">{t("common.phase", { n: 6 })}</Badge>} />
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
    </Page>
  );
}
