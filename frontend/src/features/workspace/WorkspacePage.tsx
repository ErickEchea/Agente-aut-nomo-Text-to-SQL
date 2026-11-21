import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, ChevronDown, Sparkles } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import { formatDate } from "../../lib/format";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { AgentTimeline } from "../timeline/AgentTimeline";
import { QueryBar } from "./QueryBar";
import { useRunStream, useWorkspace } from "./session";
import { TurnView } from "./TurnView";

function Examples() {
  const { t } = useTranslation();
  const { ask, busy } = useWorkspace();
  const reduced = useReducedMotion() ?? false;
  const examples = t("examples", { returnObjects: true }) as unknown as string[];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 py-6 sm:py-12">
      <div className="grid gap-3">
        <span className="flex size-10 items-center justify-center rounded-lg border border-accent/40 bg-accent-soft text-accent">
          <Sparkles aria-hidden="true" className="size-5" />
        </span>
        <h1 className="text-h1 text-fg sm:text-display">{t("workspace.examplesTitle")}</h1>
        <p className="max-w-2xl text-[0.9375rem] text-fg-secondary">{t("workspace.examplesSubtitle")}</p>
      </div>
      <section aria-labelledby="examples-title" className="grid gap-3">
        <h2 id="examples-title" className="label-micro">
          {t("workspace.examplesLabel")}
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {examples.map((example, i) => (
            <motion.li
              key={example}
              initial={reduced ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: reduced ? 0 : i * 0.04, duration: reduced ? 0 : 0.3, ease: [0.22, 1, 0.36, 1] }}
              className={cn(i === 0 && "sm:col-span-2")}
            >
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  ask(example).catch((error: unknown) => toast.error(errorMessage(error, t)));
                }}
                className={cn(
                  "group flex h-full w-full items-start justify-between gap-3 rounded-lg border border-line bg-surface-1 p-4 text-left",
                  "transition-colors hover:border-accent/50 hover:bg-surface-2 disabled:opacity-60",
                  i === 0 && "border-accent/30",
                )}
              >
                <span className={cn("text-fg-secondary group-hover:text-fg", i === 0 && "text-[0.9375rem] text-fg")}>{example}</span>
                <ArrowUpRight aria-hidden="true" className="size-4 shrink-0 text-fg-muted group-hover:text-accent" />
              </button>
            </motion.li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function WorkspacePage() {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const { turns, selectedRunId, select, openRun, streams } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [timelineOpen, setTimelineOpen] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);
  const wide = useMediaQuery("(min-width: 1280px)");

  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => endpoints.getPreferences(api) });
  const connection = useQuery({ queryKey: ["connections"], queryFn: () => endpoints.listConnections(api), staleTime: 300_000 });
  const asOf = connection.data?.[0]?.as_of;

  // /?run=<id> opens a past run (from history, dashboards or the palette).
  const runParam = params.get("run");
  useEffect(() => {
    if (!runParam) return;
    let alive = true;
    endpoints
      .getRun(api, runParam)
      .then((run) => {
        if (alive) openRun(run.id, run.conversation_id, run.question);
      })
      .catch((error: unknown) => toast.error(errorMessage(error, t)))
      .finally(() => {
        if (alive) setParams({}, { replace: true });
      });
    return () => {
      alive = false;
    };
  }, [runParam, api, openRun, setParams, t]);

  const lastRunId = turns.at(-1)?.runId;
  useEffect(() => {
    if (lastRunId) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lastRunId]);

  const selected = useRunStream(selectedRunId);
  const runningRunId = turns.find((turn) => {
    const stream = streams[turn.runId];
    return stream !== undefined && !stream.finished;
  })?.runId ?? null;

  const timeline = <AgentTimeline source={selectedRunId ? selected : null} className="h-full" />;
  const compactTimeline = <AgentTimeline source={selectedRunId ? selected : null} hideTitle />;

  return (
    <div className="grid min-h-0 flex-1 grid-rows-1 overflow-hidden xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 sm:px-6">
          <h1 className="sr-only">{t("workspace.title")}</h1>
          {turns.length === 0 ? (
            <Examples />
          ) : (
            <div className="mx-auto grid w-full max-w-4xl grid-cols-1 gap-4 pb-6">
              {selectedRunId && !wide ? (
                <div className="rounded-lg border border-line bg-surface-1">
                  <button
                    type="button"
                    aria-expanded={timelineOpen}
                    onClick={() => {
                      setTimelineOpen((v) => !v);
                    }}
                    className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-fg"
                  >
                    {t("timeline.title")}
                    <ChevronDown aria-hidden="true" className={cn("size-4 transition-transform", timelineOpen && "rotate-180")} />
                  </button>
                  {timelineOpen ? <div className="max-h-[28rem] overflow-y-auto border-t border-line">{compactTimeline}</div> : null}
                </div>
              ) : null}
              {turns.map((turn) => (
                <TurnView
                  key={turn.runId}
                  turn={turn}
                  selected={turn.runId === selectedRunId}
                  onSelect={() => {
                    select(turn.runId);
                  }}
                  preferences={preferences.data}
                />
              ))}
              <div ref={bottom} />
            </div>
          )}
        </div>
        <div className="sticky bottom-0 bg-linear-to-t from-bg via-bg/95 to-transparent px-4 pt-6 pb-4 sm:px-6">
          <div className="mx-auto w-full max-w-4xl">
            <QueryBar runningRunId={runningRunId} />
            {asOf ? <p className="mt-2 text-center text-micro text-fg-muted">{t("workspace.asOf", { date: formatDate(asOf, locale) })}</p> : null}
          </div>
        </div>
      </div>
      {wide ? <aside className="min-h-0 border-l border-line bg-surface-1">{timeline}</aside> : null}
    </div>
  );
}
