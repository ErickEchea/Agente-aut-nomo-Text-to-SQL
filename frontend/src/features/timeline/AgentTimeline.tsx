/**
 * The live agent timeline: one node per graph step with status, duration, tokens and expandable
 * output (SQL highlighted, repair diffs). Streams over SSE; finished runs replay the same events.
 */
import {
  AlertTriangle,
  BarChart3,
  Brain,
  CalendarClock,
  Check,
  CircleDashed,
  Code2,
  Database,
  Eye,
  ListTree,
  MessageSquareText,
  Play,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NodeName } from "../../api/events";
import { usePreferences } from "../../app/preferences";
import { Badge, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import { formatDuration } from "../../lib/format";
import { buildTimeline, MAIN_PATH, pendingNodes, type ItemState, type TimelineItem } from "./model";
import { NodeOutput } from "./NodeOutput";

const ICONS: Record<NodeName, LucideIcon> = {
  understand: Brain,
  retrieve_schema: Database,
  plan: ListTree,
  resolve_time: CalendarClock,
  generate_sql: Code2,
  validate: ShieldCheck,
  execute: Play,
  verify_results: Eye,
  repair: Wrench,
  visualize: BarChart3,
  explain: Sparkles,
  remember: MessageSquareText,
  respond: MessageSquareText,
};

const STATE_STYLE: Record<ItemState, string> = {
  pending: "border-line-strong bg-surface-1 text-fg-muted",
  running: "border-accent bg-accent-soft text-accent animate-[signal-pulse_1.6s_ease-out_infinite]",
  done: "border-success/50 bg-success-soft text-success",
  issue: "border-warning/60 bg-warning-soft text-warning",
  failed: "border-danger/60 bg-danger-soft text-danger",
};

function StateIcon({ state, node }: { state: ItemState; node: NodeName }) {
  if (state === "done") return <Check aria-hidden="true" />;
  if (state === "failed") return <X aria-hidden="true" />;
  if (state === "issue") return <AlertTriangle aria-hidden="true" />;
  if (state === "pending") return <CircleDashed aria-hidden="true" />;
  const Icon = ICONS[node];
  return <Icon aria-hidden="true" />;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      setNow(Date.now());
    }, 200);
    return () => {
      clearInterval(id);
    };
  }, [active]);
  return now;
}

const PER_STEP: ReadonlySet<NodeName> = new Set(["generate_sql", "validate", "execute", "verify_results", "repair"]);

function Item({ item, last, now, multiStep }: { item: TimelineItem; last: boolean; now: number; multiStep: boolean }) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const reduced = useReducedMotion() ?? false;
  const autoOpen = item.node === "repair" || item.state === "failed" || item.state === "issue";
  // Repairs, failures and issues open themselves until the user toggles the step.
  const [toggled, setToggled] = useState<boolean | null>(null);
  const open = toggled ?? autoOpen;

  const elapsed =
    item.state === "running" && item.startedAt ? Math.max(0, now - new Date(item.startedAt).getTime()) : item.durationMs;
  const expandable = item.output !== null || item.error !== null;
  const panelId = `node-${item.key}`;

  return (
    <motion.li
      layout={!reduced}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
      className="relative grid grid-cols-[2rem_1fr] gap-x-3"
    >
      {!last ? (
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-8 bottom-0 left-[15px] w-px",
            item.state === "done" ? "bg-success/40" : item.state === "running" ? "bg-accent/40" : "bg-line-strong",
          )}
        />
      ) : null}
      <span
        className={cn(
          "relative z-[1] mt-0.5 flex size-8 items-center justify-center rounded-full border [&_svg]:size-4",
          STATE_STYLE[item.state],
          reduced && "animate-none",
        )}
      >
        <StateIcon state={item.state} node={item.node} />
        <span className="sr-only">{t(`timeline.states.${item.state}`)}</span>
      </span>

      <div className="min-w-0 pb-4">
        <button
          type="button"
          disabled={!expandable}
          aria-expanded={expandable ? open : undefined}
          aria-controls={expandable ? panelId : undefined}
          onClick={() => {
            setToggled(!open);
          }}
          className="group flex w-full items-start justify-between gap-2 rounded-md text-left disabled:cursor-default"
        >
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium text-fg">{t(`timeline.nodes.${item.node}.name`)}</span>
              {multiStep && item.step !== null && PER_STEP.has(item.node) ? <Badge>{t("timeline.step", { n: item.step + 1 })}</Badge> : null}
              {item.attempt !== null && item.attempt > 1 && (item.node === "generate_sql" || item.node === "repair" || item.node === "validate" || item.node === "execute") ? (
                <Badge tone="warning">{t("timeline.attempt", { n: item.attempt })}</Badge>
              ) : null}
            </span>
            <span className="block truncate text-small text-fg-muted">{t(`timeline.nodes.${item.node}.hint`)}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 pt-0.5">
            <span className="text-right">
              <span className={cn("figures block text-small", item.state === "running" ? "text-accent" : "text-fg-secondary")}>
                {formatDuration(elapsed, locale)}
              </span>
              {item.tokens > 0 ? (
                <span className="figures block text-micro text-fg-muted">
                  {t("timeline.tokens", { count: item.tokens })}
                </span>
              ) : null}
            </span>
            {expandable ? (
              <ChevronDown
                aria-hidden="true"
                className={cn("size-4 text-fg-muted transition-transform group-hover:text-fg", open && "rotate-180")}
              />
            ) : null}
          </span>
        </button>

        <AnimatePresence initial={false}>
          {open && expandable ? (
            <motion.div
              id={panelId}
              key="panel"
              initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
              animate={reduced ? { opacity: 1 } : { opacity: 1, height: "auto" }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
              transition={{ duration: reduced ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="mt-2 rounded-md border border-line bg-surface-2/60 p-3">
                <NodeOutput item={item} />
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </motion.li>
  );
}

function Pending({ node, last }: { node: NodeName; last: boolean }) {
  const { t } = useTranslation();
  return (
    <li className="relative grid grid-cols-[2rem_1fr] gap-x-3">
      {!last ? <span aria-hidden="true" className="absolute top-8 bottom-0 left-[15px] w-px bg-line" /> : null}
      <span className={cn("mt-0.5 flex size-8 items-center justify-center rounded-full border border-dashed [&_svg]:size-4", STATE_STYLE.pending)}>
        <CircleDashed aria-hidden="true" />
        <span className="sr-only">{t("timeline.states.pending")}</span>
      </span>
      <div className="pb-4">
        <span className="block text-fg-muted">{t(`timeline.nodes.${node}.name`)}</span>
        <span className="block text-small text-fg-muted">{t(`timeline.nodes.${node}.hint`)}</span>
      </div>
    </li>
  );
}

export interface TimelineSource {
  events: Parameters<typeof buildTimeline>[0];
  streaming: boolean;
  error: unknown;
}

export function AgentTimeline({
  source,
  className,
  hideTitle = false,
}: {
  source: TimelineSource | null;
  className?: string;
  /** The collapsible mobile panel already shows the title on its toggle. */
  hideTitle?: boolean;
}) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const model = buildTimeline(source?.events ?? []);
  const pending = pendingNodes(model);
  const live = !model.finished && model.items.length > 0;
  const now = useNow(live);
  const multiStep = model.items.some((item) => PER_STEP.has(item.node) && (item.step ?? 0) > 0);

  return (
    <section aria-labelledby="timeline-title" className={cn("flex flex-col", className)}>
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <h2 id="timeline-title" className={cn("text-h3 whitespace-nowrap text-fg", hideTitle && "sr-only")}>
          {t("timeline.title")}
        </h2>
        {source ? (
          live ? (
            <Badge tone="accent">
              <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-accent motion-reduce:animate-none" />
              {t("timeline.live")}
            </Badge>
          ) : model.finished ? (
            <span className="figures grid text-right leading-tight">
              <span className="text-small text-fg-secondary">{t("timeline.total", { duration: formatDuration(model.totalMs, locale) })}</span>
              {model.totalTokens > 0 ? <span className="text-micro text-fg-muted">{t("timeline.tokens", { count: model.totalTokens })}</span> : null}
            </span>
          ) : null
        ) : null}
      </header>

      <div className="flex-1 overflow-y-auto px-4 pt-4" aria-live="polite" aria-busy={live} tabIndex={0}>
        {!source ? (
          <>
            <p className="mb-4 text-small text-fg-muted">{t("timeline.empty")}</p>
            <ol className="grid">
              {MAIN_PATH.map((node, i) => (
                <Pending key={node} node={node} last={i === MAIN_PATH.length - 1} />
              ))}
            </ol>
          </>
        ) : model.items.length === 0 && !source.error ? (
          <div className="grid gap-4" role="status">
            <span className="sr-only">{t("timeline.waiting")}</span>
            {[0, 1, 2].map((i) => (
              <div key={i} className="grid grid-cols-[2rem_1fr] gap-3">
                <Skeleton className="size-8 rounded-full" />
                <div className="grid gap-1.5">
                  <Skeleton className="h-3.5 w-32" />
                  <Skeleton className="h-3 w-48" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <ol className="grid">
            {model.items.map((item, i) => (
              <Item key={item.key} item={item} now={now} multiStep={multiStep} last={i === model.items.length - 1 && pending.length === 0} />
            ))}
            {pending.map((node, i) => (
              <Pending key={`pending-${node}`} node={node} last={i === pending.length - 1} />
            ))}
          </ol>
        )}
        {source?.error ? (
          <p role="alert" className="mb-4 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-small text-danger">
            {errorMessage(source.error, t) === t("errors.unknown") ? t("errors.stream") : errorMessage(source.error, t)}
          </p>
        ) : null}
      </div>
    </section>
  );
}
