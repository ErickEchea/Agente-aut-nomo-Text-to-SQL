import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Database, Fingerprint, Lock, RefreshCw, Table2, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import type { ConnectionDetail, ConnectionSummary } from "../../api/types";
import { useApi, useCan } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { ErrorState, Page, PageHeader } from "../../components/Page";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "../../components/ui/overlays";
import { Badge, Panel, PanelHeader, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import { formatDate, formatDateTime, formatDuration, formatNumber } from "../../lib/format";
import { AddConnectionDialog } from "./AddConnectionDialog";

const INDEX_TONE = { ready: "success", pending: "neutral", indexing: "info", failed: "danger" } as const;

function Fact({ label, value, mono = false }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  return (
    <div className="grid min-w-0 gap-0.5">
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

function SourceCard({ source, selected, onSelect }: { source: ConnectionSummary; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "grid w-full gap-2 rounded-lg border p-3 text-left transition-colors",
        selected ? "border-accent/60 bg-accent-soft" : "border-line bg-surface-1 hover:border-line-strong",
      )}
    >
      <span className="flex items-center gap-2">
        <Database aria-hidden="true" className={cn("size-4 shrink-0", selected ? "text-accent" : "text-fg-muted")} />
        <span className="min-w-0 flex-1 truncate font-medium text-fg">{source.name}</span>
      </span>
      <span className="flex flex-wrap items-center gap-1.5">
        <Badge>{source.engine}</Badge>
        {source.builtin ? <Badge tone="accent">{t("connections.builtin")}</Badge> : null}
        <Badge tone={INDEX_TONE[source.index_status]}>{t(`connections.indexState.${source.index_status}`)}</Badge>
        {!source.read_only ? (
          <Badge tone="warning">
            <TriangleAlert aria-hidden="true" />
            {t("connections.writableBadge")}
          </Badge>
        ) : null}
      </span>
      <span className="truncate font-mono text-micro text-fg-muted">
        {source.database}
        {source.kind !== "sqlite" ? ` · ${source.schema_name}` : ""}
      </span>
    </button>
  );
}

function SourceActions({ source }: { source: ConnectionSummary }) {
  const { t } = useTranslation();
  const api = useApi();
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["connections"] });
    void queryClient.invalidateQueries({ queryKey: ["connection", source.key] });
  };
  const reindex = useMutation({ mutationFn: () => endpoints.reindexConnection(api, source.key), onSuccess: refresh, onError: (e) => toast.error(errorMessage(e, t)) });
  const remove = useMutation({ mutationFn: () => endpoints.deleteConnection(api, source.key), onSuccess: refresh, onError: (e) => toast.error(errorMessage(e, t)) });
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={reindex.isPending || source.index_status === "indexing"} onClick={() => { reindex.mutate(); }}>
        <RefreshCw />
        {t("connections.reindex")}
      </Button>
      {!source.builtin ? (
        <Dialog>
          <DialogTrigger asChild>
            <Button size="sm" variant="danger">
              <Trash2 />
              {t("connections.remove")}
            </Button>
          </DialogTrigger>
          <DialogContent title={t("connections.deleteTitle", { name: source.name })} description={t("connections.deleteBody")}>
            <div className="flex justify-end">
              <Button variant="danger" disabled={remove.isPending} onClick={() => { remove.mutate(); }}>
                <Trash2 />
                {t("connections.remove")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}

function SourceDetail({ summary }: { summary: ConnectionSummary }) {
  const { t } = useTranslation();
  const api = useApi();
  const { admin } = useCan();
  const { locale } = usePreferences();
  const detail = useQuery({
    queryKey: ["connection", summary.key, summary.index_status],
    queryFn: () => endpoints.getConnection(api, summary.key),
  });

  if (detail.isPending) {
    return <Skeleton className="h-96" />;
  }
  if (detail.isError) {
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  const c: ConnectionDetail = detail.data;
  const documents = Object.values(c.index.documents).reduce((a, b) => a + b, 0);
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <Panel aria-labelledby={`conn-${c.key}`}>
        <PanelHeader className="flex-wrap">
          <h2 id={`conn-${c.key}`} className="flex min-w-0 items-center gap-2 text-h3 text-fg">
            <Database aria-hidden="true" className="size-4 shrink-0 text-accent" />
            <span className="truncate">{c.name}</span>
          </h2>
          {c.read_only ? (
            <Badge tone="success">
              <Lock aria-hidden="true" />
              {t("connections.readOnly")}
            </Badge>
          ) : (
            <Badge tone="warning">
              <TriangleAlert aria-hidden="true" />
              {t("connections.writableBadge")}
            </Badge>
          )}
        </PanelHeader>
        <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3">
          <Fact label={t("connections.dialect")} value={c.engine} />
          <Fact label={t("connections.database")} value={c.database} mono />
          <Fact label={t("connections.schema")} value={c.schema_name} mono />
          <Fact label={t("connections.asOf")} value={c.as_of ? formatDate(c.as_of, locale) : null} />
          <Fact label={t("connections.model")} value={c.llm_model} mono />
          {c.user ? <Fact label={t("connections.user")} value={c.user} mono /> : null}
          {c.host ? <Fact label={t("connections.host")} value={`${c.host}:${String(c.port ?? "")}`} mono /> : null}
        </dl>
        {c.index_error ? <p className="border-t border-line px-4 py-3 text-small text-danger">{c.index_error}</p> : null}
        {admin ? (
          <div className="border-t border-line px-4 py-3">
            <SourceActions source={summary} />
          </div>
        ) : null}
      </Panel>

      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel aria-labelledby={`tables-${c.key}`}>
          <PanelHeader>
            <h3 id={`tables-${c.key}`} className="flex items-center gap-2 text-h3 text-fg">
              <Table2 aria-hidden="true" className="size-4 text-fg-muted" />
              {t("connections.tables")}
            </h3>
            <span className="figures text-small text-fg-muted">{c.tables.length}</span>
          </PanelHeader>
          <ul className="divide-y divide-line">
            {c.tables.map((table) => (
              <li key={table.name} className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_1fr_auto] sm:items-baseline sm:gap-4">
                <span className="truncate font-mono text-small text-fg">{table.name}</span>
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
            <h3 id={`index-${c.key}`} className="flex items-center gap-2 text-h3 text-fg">
              <Fingerprint aria-hidden="true" className="size-4 text-fg-muted" />
              {t("connections.index")}
            </h3>
            <Badge tone={INDEX_TONE[c.index_status]}>{t(`connections.indexState.${c.index_status}`)}</Badge>
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
}

export function ConnectionsPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { admin } = useCan();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const sources = useQuery({
    queryKey: ["connections"],
    queryFn: () => endpoints.listConnections(api),
    // Poll while a schema is being indexed.
    refetchInterval: (query) => (query.state.data?.some((s) => s.index_status === "indexing") ? 2000 : false),
  });
  const list = sources.data ?? [];
  const selected = list.find((s) => s.key === selectedKey) ?? list[0];

  return (
    <Page>
      <PageHeader title={t("connections.title")} subtitle={t("connections.subtitle")} actions={admin ? <AddConnectionDialog /> : null} />
      {sources.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Skeleton className="h-64" />
          <Skeleton className="h-96" />
        </div>
      ) : sources.isError ? (
        <ErrorState error={sources.error} onRetry={() => void sources.refetch()} />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="grid content-start gap-4">
            <section aria-labelledby="sources-title" className="grid gap-2">
              <h2 id="sources-title" className="label-micro">
                {t("connections.sources")}
              </h2>
              <ul className="grid gap-2">
                {list.map((source) => (
                  <li key={source.key}>
                    <SourceCard
                      source={source}
                      selected={source.key === selected?.key}
                      onSelect={() => {
                        setSelectedKey(source.key);
                      }}
                    />
                  </li>
                ))}
              </ul>
            </section>
            <Health />
          </div>
          {selected ? <SourceDetail key={selected.key} summary={selected} /> : null}
        </div>
      )}
    </Page>
  );
}
