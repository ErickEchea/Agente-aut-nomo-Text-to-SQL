/** One question/answer turn of the conversation. */
import { useQuery } from "@tanstack/react-query";
import { Ban, CircleHelp, OctagonX, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import type { Preferences, RunOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { Button } from "../../components/ui/button";
import { Badge, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import { formatDuration } from "../../lib/format";
import { RunAnswer } from "../results/RunAnswer";
import { buildTimeline } from "../timeline/model";
import { useRunStream, useWorkspace, type Turn } from "./session";

const STATUS_TONE = {
  answered: "success",
  clarification: "warning",
  refused: "danger",
  failed: "danger",
  cancelled: "neutral",
} as const;

function Notice({ icon: Icon, title, body, tone }: { icon: typeof Ban; title: string; body: string; tone: "danger" | "neutral" }) {
  return (
    <div className={cn("flex gap-3 rounded-lg border p-4", tone === "danger" ? "border-danger/40 bg-danger-soft/50" : "border-line bg-surface-1")}>
      <Icon aria-hidden="true" className={cn("mt-0.5 size-5 shrink-0", tone === "danger" ? "text-danger" : "text-fg-muted")} />
      <div className="grid gap-1">
        <p className="font-medium text-fg">{title}</p>
        <p className="text-small text-fg-secondary">{body}</p>
      </div>
    </div>
  );
}

function Outcome({ run, preferences }: { run: RunOut; preferences: Preferences | undefined }) {
  const { t } = useTranslation();
  const { ask, busy } = useWorkspace();
  const result = run.result;
  const status = result?.status ?? run.status;

  if (status === "answered" && result) return <RunAnswer run={run} preferences={preferences} />;

  if (status === "clarification" && result?.clarification) {
    return (
      <div className="grid gap-3 rounded-lg border border-warning/40 bg-warning-soft/40 p-4">
        <div className="flex gap-3">
          <CircleHelp aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-warning" />
          <div className="grid gap-1">
            <p className="font-medium text-fg">{t("results.clarifyTitle")}</p>
            <p className="text-fg-secondary">{result.clarification.question}</p>
          </div>
        </div>
        {result.clarification.options.length > 0 ? (
          <div className="flex flex-wrap gap-2 pl-8">
            {result.clarification.options.map((option) => (
              <Button
                key={option}
                size="sm"
                disabled={busy}
                onClick={() => {
                  ask(option).catch((error: unknown) => toast.error(errorMessage(error, t)));
                }}
              >
                {option}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
  if (status === "refused") {
    return <Notice icon={ShieldAlert} tone="danger" title={t("results.refusedTitle")} body={result?.answer || t("results.refusedBody")} />;
  }
  if (status === "cancelled") {
    return <Notice icon={Ban} tone="neutral" title={t("results.cancelledTitle")} body={result?.answer ?? ""} />;
  }
  return <Notice icon={OctagonX} tone="danger" title={t("results.failedTitle")} body={result?.answer || t("results.failedBody")} />;
}

export function TurnView({
  turn,
  selected,
  onSelect,
  preferences,
}: {
  turn: Turn;
  selected: boolean;
  onSelect: () => void;
  preferences: Preferences | undefined;
}) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const api = useApi();
  const stream = useRunStream(turn.runId);
  const model = buildTimeline(stream.events);
  const finished = stream.finished;

  const run = useQuery({
    queryKey: ["run", turn.runId],
    queryFn: ({ signal }) => endpoints.getRun(api, turn.runId, signal),
    enabled: finished,
    staleTime: Infinity,
  });

  const current = model.items.findLast((item) => item.state === "running");
  const status = run.data?.result?.status ?? (finished ? model.status : null);

  return (
    <article
      aria-busy={!finished}
      className={cn(
        "grid min-w-0 grid-cols-1 gap-4 rounded-xl border p-4 transition-colors sm:p-5",
        selected ? "border-line-strong bg-surface-1/60" : "border-transparent",
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <button type="button" onClick={onSelect} className="min-w-0 text-left" aria-pressed={selected}>
          <span className="label-micro block">{t("workspace.questionLabel")}</span>
          <span className="block text-[0.9375rem] font-medium text-fg">{turn.question}</span>
        </button>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {status ? (
            <Badge tone={STATUS_TONE[status as keyof typeof STATUS_TONE]}>{t(`status.${status}`)}</Badge>
          ) : (
            <Badge tone="accent">
              <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-accent motion-reduce:animate-none" />
              {t("status.running")}
            </Badge>
          )}
          {model.totalMs !== null ? <span className="figures text-micro text-fg-muted">{formatDuration(model.totalMs, locale)}</span> : null}
        </div>
      </header>

      {!finished ? (
        <div className="grid gap-3" role="status">
          <p className="text-small text-fg-secondary">
            {current ? (
              <>
                <span className="text-accent">{t(`timeline.nodes.${current.node}.name`)}</span>
                {" · "}
                {t(`timeline.nodes.${current.node}.hint`)}
              </>
            ) : stream.error ? (
              <span className="text-danger">{errorMessage(stream.error, t)}</span>
            ) : (
              t("timeline.waiting")
            )}
          </p>
          <Skeleton className="h-6 w-3/4" />
          <div className="grid gap-3 sm:grid-cols-[1.4fr_1fr]">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
          <Skeleton className="h-48" />
        </div>
      ) : run.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-40" />
        </div>
      ) : run.isError ? (
        <p role="alert" className="text-danger">
          {errorMessage(run.error, t)}
        </p>
      ) : (
        <Outcome run={run.data} preferences={preferences} />
      )}
    </article>
  );
}
