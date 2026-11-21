import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, History, Repeat, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { EmptyState, ErrorState, Page, PageHeader } from "../../components/Page";
import { Button } from "../../components/ui/button";
import { Badge, Panel, PanelHeader, Skeleton } from "../../components/ui/primitives";
import { errorMessage } from "../../lib/errors";
import { formatDuration, formatRelative } from "../../lib/format";
import { useWorkspace } from "../workspace/session";

const TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "accent"> = {
  answered: "success",
  clarification: "warning",
  refused: "danger",
  failed: "danger",
  cancelled: "neutral",
  running: "accent",
};

export function HistoryPage() {
  const { t } = useTranslation();
  const api = useApi();
  const navigate = useNavigate();
  const { locale } = usePreferences();
  const { ask, newConversation, busy } = useWorkspace();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => endpoints.listRuns(api, 100) });
  const frequent = useQuery({ queryKey: ["frequent"], queryFn: () => endpoints.frequentQuestions(api) });

  const askAgain = (question: string) => {
    newConversation();
    void navigate("/");
    ask(question).catch((error: unknown) => toast.error(errorMessage(error, t)));
  };

  return (
    <Page>
      <PageHeader title={t("history.title")} subtitle={t("history.subtitle")} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel aria-labelledby="recent-title">
          <PanelHeader>
            <h2 id="recent-title" className="flex items-center gap-2 text-h3 text-fg">
              <History aria-hidden="true" className="size-4 text-fg-muted" />
              {t("history.recent")}
            </h2>
          </PanelHeader>
          {runs.isPending ? (
            <div className="grid gap-2 p-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : runs.isError ? (
            <div className="p-4">
              <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
            </div>
          ) : runs.data.length === 0 ? (
            <EmptyState icon={History} title={t("history.emptyRecent")} className="m-4" />
          ) : (
            <ul className="divide-y divide-line">
              {runs.data.map((run) => (
                <li key={run.id}>
                  <Link to={`/?run=${run.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-fg">{run.question}</span>
                      <span className="figures block text-micro text-fg-muted">
                        {formatRelative(run.created_at, locale)} · {formatDuration(run.duration_ms, locale)}
                      </span>
                    </span>
                    <Badge tone={TONE[run.status] ?? "neutral"}>{t(`status.${run.status}`)}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid content-start gap-6">
          <Panel aria-labelledby="frequent-title">
            <PanelHeader>
              <h2 id="frequent-title" className="flex items-center gap-2 text-h3 text-fg">
                <Repeat aria-hidden="true" className="size-4 text-fg-muted" />
                {t("history.frequent")}
              </h2>
            </PanelHeader>
            {frequent.isPending ? (
              <div className="grid gap-2 p-4">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </div>
            ) : frequent.isError ? (
              <div className="p-4">
                <ErrorState error={frequent.error} onRetry={() => void frequent.refetch()} />
              </div>
            ) : frequent.data.length === 0 ? (
              <p className="p-4 text-small text-fg-muted">{t("history.emptyFrequent")}</p>
            ) : (
              <ul className="divide-y divide-line">
                {frequent.data.map((q) => (
                  <li key={q.question} className="flex items-center gap-3 px-4 py-3">
                    <span className="min-w-0 flex-1">
                      <span className="block text-small text-fg">{q.question}</span>
                      <span className="block text-micro text-fg-muted">{t("history.timesAsked", { count: q.times_asked })}</span>
                    </span>
                    <Button variant="ghost" size="icon-sm" aria-label={t("history.ask")} disabled={busy} onClick={() => { askAgain(q.question); }}>
                      <RotateCcw />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel className="p-4">
            <h2 className="mb-2 flex items-center gap-2 text-h3 text-fg">
              <BrainCircuit aria-hidden="true" className="size-4 text-accent" />
              {t("history.memoryTitle")}
            </h2>
            <p className="text-small text-fg-secondary">{t("history.memoryBody")}</p>
          </Panel>
        </div>
      </div>
    </Page>
  );
}
