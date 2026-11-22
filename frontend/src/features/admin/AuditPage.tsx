import { useInfiniteQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { EmptyState, ErrorState, Page, PageHeader } from "../../components/Page";
import { Button } from "../../components/ui/button";
import { Badge, Panel, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { formatDateTime, formatDuration } from "../../lib/format";
import { SqlBlock } from "../results/SqlBlock";

const PAGE = 50;
const OUTCOMES = ["ok", "error", "denied", "rejected"] as const;
const TONE: Record<string, "success" | "danger" | "warning"> = {
  ok: "success",
  error: "danger",
  denied: "warning",
  rejected: "danger",
};

export function AuditPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const audit = useInfiniteQuery({
    queryKey: ["audit", outcome],
    queryFn: ({ pageParam }) => endpoints.listAudit(api, { limit: PAGE, beforeId: pageParam, outcome }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.length === PAGE ? (last.at(-1)?.id ?? null) : null),
  });
  const entries = audit.data?.pages.flat() ?? [];

  return (
    <Page>
      <PageHeader title={t("audit.title")} subtitle={t("audit.subtitle")} />
      <div role="group" aria-label={t("audit.outcome")} className="flex flex-wrap gap-1">
        {[null, ...OUTCOMES].map((value) => (
          <Button
            key={value ?? "all"}
            size="sm"
            variant={outcome === value ? "primary" : "secondary"}
            aria-pressed={outcome === value}
            onClick={() => {
              setOutcome(value);
            }}
          >
            {value ? t(`audit.outcomes.${value}`) : t("audit.all")}
          </Button>
        ))}
      </div>
      {audit.isPending ? (
        <Skeleton className="h-80" />
      ) : audit.isError ? (
        <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />
      ) : entries.length === 0 ? (
        <EmptyState icon={ScrollText} title={t("audit.empty")} />
      ) : (
        <Panel className="overflow-hidden">
          <div tabIndex={0} role="region" aria-label={t("audit.tableLabel")} className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-small">
              <thead className="bg-surface-2 text-left text-fg-muted">
                <tr>
                  {(["time", "action", "question", "rows", "duration", "ip"] as const).map((col) => (
                    <th key={col} scope="col" className={cn("px-3 py-2 font-medium", (col === "rows" || col === "duration") && "text-right")}>
                      {t(`audit.columns.${col}`)}
                    </th>
                  ))}
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("audit.outcome")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <Fragment key={entry.id}>
                    <tr className="border-t border-line align-top hover:bg-surface-2/60">
                      <td className="figures px-3 py-2 whitespace-nowrap text-fg-secondary">{formatDateTime(entry.created_at, locale)}</td>
                      <td className="px-3 py-2 font-mono text-fg">{entry.action}</td>
                      <td className="max-w-[22rem] px-3 py-2 text-fg-secondary">
                        <span className="line-clamp-2">{entry.question ?? "—"}</span>
                        {entry.sql ? (
                          <button
                            type="button"
                            aria-expanded={expanded === entry.id}
                            onClick={() => {
                              setExpanded(expanded === entry.id ? null : entry.id);
                            }}
                            className="mt-1 text-micro text-accent hover:underline"
                          >
                            {t("audit.showSql")}
                          </button>
                        ) : null}
                      </td>
                      <td className="figures px-3 py-2 text-right text-fg-secondary">{entry.row_count ?? "—"}</td>
                      <td className="figures px-3 py-2 text-right whitespace-nowrap text-fg-secondary">{formatDuration(entry.duration_ms, locale)}</td>
                      <td className="figures px-3 py-2 text-fg-muted">{entry.client_ip ?? "—"}</td>
                      <td className="px-3 py-2">
                        <Badge tone={TONE[entry.outcome] ?? "neutral"}>
                          {t(`audit.outcomes.${entry.outcome}`, { defaultValue: entry.outcome })}
                        </Badge>
                        {entry.error_code ? <span className="mt-1 block font-mono text-micro text-fg-muted">{entry.error_code}</span> : null}
                      </td>
                    </tr>
                    {expanded === entry.id && entry.sql ? (
                      <tr className="bg-surface-2/40">
                        <td colSpan={7} className="px-3 pb-3">
                          <SqlBlock sql={entry.sql} compact />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {audit.hasNextPage ? (
            <div className="border-t border-line p-3 text-center">
              <Button size="sm" disabled={audit.isFetchingNextPage} onClick={() => void audit.fetchNextPage()}>
                {t("audit.loadMore")}
              </Button>
            </div>
          ) : null}
        </Panel>
      )}
    </Page>
  );
}
