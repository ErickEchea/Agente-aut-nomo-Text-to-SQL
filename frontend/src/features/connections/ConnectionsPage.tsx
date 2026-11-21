import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Fingerprint, Lock, Table2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import { useApi } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState, Page, PageHeader } from "../../components/Page";
import { Badge, Panel, PanelHeader, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { formatDate, formatDateTime, formatDuration, formatNumber } from "../../lib/format";

function Fact({ label, value, mono = false }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  return (
    <div className="grid gap-0.5">
      <dt className="label-micro">{label}</dt>
      <dd className={cn("truncate text-fg", mono && "font-mono text-small")}>{value ?? "—"}</dd>
    </div>
  );
}

function Health() {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const ready = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => endpoints.readiness(api, signal), refetchInterval: 30_000, retry: false });
  return (
    <Panel aria-labelledby="health-title">
      <PanelHeader>
        <h2 id="health-title" className="flex items-center gap-2 text-h3 text-fg">
          <Activity aria-hidden="true" className="size-4 text-fg-muted" />
          {t("connections.health")}
        </h2>
        {ready.data ? (
          <Badge tone={ready.data.status === "ready" ? "success" : "warning"}>
            {ready.data.status === "ready" ? t("topbar.healthy") : t("topbar.degraded")}
          </Badge>
        ) : null}
      </PanelHeader>
      {ready.isError ? (
        <div className="p-4">
          <ErrorState error={ready.error} onRetry={() => void ready.refetch()} />
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {(["app_db", "demo_db", "ollama"] as const).map((name) => {
            const check = ready.data?.checks[name];
            return (
              <li key={name} className="flex items-center gap-3 px-4 py-3">
                <span className={cn("size-2 shrink-0 rounded-full", !check ? "bg-fg-muted" : check.ok ? "bg-success" : "bg-danger")} aria-hidden="true" />
                <span className="flex-1 text-fg">{t(`connections.checks.${name}`)}</span>
                {check ? (
                  <span className="figures text-small text-fg-muted">
                    {check.ok ? formatDuration(check.latency_ms, locale) : t("timeline.states.failed")}
                  </span>
                ) : (
                  <Skeleton className="h-4 w-12" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export function ConnectionsPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { locale } = usePreferences();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => endpoints.listConnections(api) });

  return (
    <Page>
      <PageHeader title={t("connections.title")} subtitle={t("connections.subtitle")} />
      {connections.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : connections.isError ? (
        <ErrorState error={connections.error} onRetry={() => void connections.refetch()} />
      ) : (
        connections.data.map((c) => {
          const documents = Object.values(c.index.documents).reduce((a, b) => a + b, 0);
          return (
            <div key={c.key} className="grid gap-6">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <Panel aria-labelledby={`conn-${c.key}`}>
                  <PanelHeader>
                    <h2 id={`conn-${c.key}`} className="flex items-center gap-2 font-mono text-h3 text-fg">
                      <Database aria-hidden="true" className="size-4 text-accent" />
                      {c.key}
                    </h2>
                    <Badge tone="success">
                      <Lock aria-hidden="true" />
                      {t("connections.readOnly")}
                    </Badge>
                  </PanelHeader>
                  <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3">
                    <Fact label={t("connections.dialect")} value={c.dialect} mono />
                    <Fact label={t("connections.database")} value={c.database} mono />
                    <Fact label={t("connections.schema")} value={c.schema_name} mono />
                    <Fact label={t("connections.asOf")} value={formatDate(c.as_of, locale)} />
                    <Fact label={t("connections.model")} value={c.llm_model} mono />
                    {c.user ? <Fact label={t("connections.user")} value={c.user} mono /> : null}
                    {c.host ? <Fact label={t("connections.host")} value={`${c.host}:${String(c.port)}`} mono /> : null}
                  </dl>
                  <p className="border-t border-line px-4 py-3 text-small text-fg-muted">{t("connections.multiDb")}</p>
                </Panel>
                <Health />
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <Panel aria-labelledby={`tables-${c.key}`}>
                  <PanelHeader>
                    <h2 id={`tables-${c.key}`} className="flex items-center gap-2 text-h3 text-fg">
                      <Table2 aria-hidden="true" className="size-4 text-fg-muted" />
                      {t("connections.tables")}
                    </h2>
                    <span className="figures text-small text-fg-muted">{c.tables.length}</span>
                  </PanelHeader>
                  <ul className="divide-y divide-line">
                    {c.tables.map((table) => (
                      <li key={table.name} className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_1fr_auto] sm:items-baseline sm:gap-4">
                        <span className="font-mono text-small text-fg">{table.name}</span>
                        <span className="text-small text-fg-secondary">
                          {table.comment}
                          {table.references.length > 0 ? (
                            <span className="mt-1 block text-micro text-fg-muted">
                              {t("connections.references")}: <span className="font-mono">{table.references.join(", ")}</span>
                            </span>
                          ) : null}
                        </span>
                        <span className="figures text-micro text-fg-muted sm:text-right">
                          {t("connections.rows", { value: formatNumber(table.row_estimate, locale, "integer") })}
                          <br className="hidden sm:block" /> {t("connections.columns", { count: table.columns })}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Panel>

                <Panel aria-labelledby={`index-${c.key}`} className="self-start">
                  <PanelHeader>
                    <h2 id={`index-${c.key}`} className="flex items-center gap-2 text-h3 text-fg">
                      <Fingerprint aria-hidden="true" className="size-4 text-fg-muted" />
                      {t("connections.index")}
                    </h2>
                  </PanelHeader>
                  <dl className="grid gap-4 p-4">
                    <Fact label={t("connections.embedding")} value={c.index.embedding_model} mono />
                    <div className="grid gap-1.5">
                      <dt className="label-micro">{t("connections.documents")}</dt>
                      <dd className="grid gap-1.5">
                        <span className="figures text-h2 text-fg">{formatNumber(documents, locale, "integer")}</span>
                        <span className="flex h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
                          {Object.entries(c.index.documents).map(([type, n], i) => (
                            <span key={type} className="h-full border-r-2 border-surface-1 last:border-r-0" style={{ width: `${(n / Math.max(documents, 1)) * 100}%`, background: `var(--data-${i + 1})` }} />
                          ))}
                        </span>
                        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-micro text-fg-muted">
                          {Object.entries(c.index.documents).map(([type, n], i) => (
                            <li key={type} className="flex items-center gap-1.5">
                              <span aria-hidden="true" className="size-2 rounded-full" style={{ background: `var(--data-${i + 1})` }} />
                              {t(`connections.docTypes.${type}`, { defaultValue: type })} <span className="figures text-fg-secondary">{n}</span>
                            </li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                    <Fact label={t("connections.verifiedExamples")} value={c.index.verified_examples} />
                    <Fact label={t("connections.fingerprint")} value={c.index.fingerprint?.slice(0, 16) ?? null} mono />
                    <Fact label={t("connections.builtAt")} value={c.index.built_at ? formatDateTime(c.index.built_at, locale) : null} />
                  </dl>
                </Panel>
              </div>
            </div>
          );
        })
      )}
    </Page>
  );
}
