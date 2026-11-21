import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, Ellipsis, ExternalLink, LayoutDashboard, Lock, PinOff, Plus, Trash2, Users } from "lucide-react";
import { useId, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import type { DashboardItemOut, DashboardOut } from "../../api/types";
import { useApi, useCan } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { EmptyState, ErrorState, Page, PageHeader } from "../../components/Page";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogTrigger, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Switch } from "../../components/ui/overlays";
import { Badge, Input, Skeleton } from "../../components/ui/primitives";
import { errorMessage } from "../../lib/errors";
import { formatRelative } from "../../lib/format";
import { LazyChartView } from "../results/LazyChart";
import { DataTable } from "../results/DataTable";
import { KpiCards } from "../results/KpiCards";
import { isChartable } from "../results/chart-option";

function NewDashboardDialog() {
  const { t } = useTranslation();
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const ids = { name: useId(), shared: useId() };
  const create = useMutation({
    mutationFn: () => endpoints.createDashboard(api, name.trim(), shared),
    onSuccess: (dashboard) => {
      void queryClient.invalidateQueries({ queryKey: ["dashboards"] });
      setOpen(false);
      setName("");
      void navigate(`/dashboards/${dashboard.id}`);
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });
  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary">
          <Plus />
          {t("dashboards.new")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("dashboards.new")}>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <label htmlFor={ids.name} className="text-small text-fg-secondary">
              {t("dashboards.name")}
            </label>
            <Input id={ids.name} value={name} maxLength={120} autoFocus onChange={(e) => { setName(e.target.value); }} />
          </div>
          <div className="flex items-start justify-between gap-4">
            <label htmlFor={ids.shared} className="grid gap-0.5">
              <span className="text-fg">{t("dashboards.shared")}</span>
              <span className="text-small text-fg-muted">{t("dashboards.sharedHint")}</span>
            </label>
            <Switch id={ids.shared} checked={shared} onCheckedChange={setShared} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setOpen(false); }}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
              {t("common.create")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DashboardsPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { contribute } = useCan();
  const { locale } = usePreferences();
  const dashboards = useQuery({ queryKey: ["dashboards"], queryFn: () => endpoints.listDashboards(api) });

  return (
    <Page>
      <PageHeader title={t("dashboards.title")} subtitle={t("dashboards.subtitle")} actions={contribute ? <NewDashboardDialog /> : null} />
      {dashboards.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : dashboards.isError ? (
        <ErrorState error={dashboards.error} onRetry={() => void dashboards.refetch()} />
      ) : dashboards.data.length === 0 ? (
        <EmptyState
          icon={LayoutDashboard}
          title={t("dashboards.emptyTitle")}
          body={t("dashboards.emptyBody")}
          action={
            <Button asChild variant="secondary">
              <Link to="/">{t("dashboards.goToWorkspace")}</Link>
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {dashboards.data.map((d) => (
            <li key={d.id}>
              <Link
                to={`/dashboards/${d.id}`}
                className="group flex h-full flex-col gap-3 rounded-lg border border-line bg-surface-1 p-4 transition-colors hover:border-accent/50 hover:bg-surface-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-display text-h3 text-fg">{d.name}</span>
                  <LayoutDashboard aria-hidden="true" className="size-4 text-fg-muted group-hover:text-accent" />
                </div>
                <div className="mt-auto flex flex-wrap items-center gap-2">
                  <Badge tone={d.shared ? "info" : "neutral"}>
                    {d.shared ? <Users aria-hidden="true" /> : <Lock aria-hidden="true" />}
                    {d.shared ? t("dashboards.shared") : t("dashboards.private")}
                  </Badge>
                  <span className="text-small text-fg-muted">{t("dashboards.items", { count: d.item_count })}</span>
                  {!d.editable ? <span className="text-small text-fg-muted">· {t("dashboards.owner", { name: d.owner_name })}</span> : null}
                  <span className="ml-auto text-micro text-fg-muted">{formatRelative(d.created_at, locale)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}

function ItemCard({
  item,
  dashboard,
  index,
  onMove,
}: {
  item: DashboardItemOut;
  dashboard: DashboardOut;
  index: number;
  onMove: (from: number, to: number) => void;
}) {
  const { t } = useTranslation();
  const api = useApi();
  const queryClient = useQueryClient();
  const unpin = useMutation({
    mutationFn: () => endpoints.unpinItem(api, dashboard.id, item.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["dashboard", dashboard.id] }),
    onError: (error) => toast.error(errorMessage(error, t)),
  });
  const chart = item.chart;
  const result = item.result;
  const wide = result !== null && (isChartable(chart) || result.columns.length > 3);

  return (
    <li className={wide ? "lg:col-span-2" : undefined}>
      <article className="flex h-full flex-col rounded-lg border border-line bg-surface-1">
        <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate font-display text-h3 text-fg">{item.title}</h2>
            {item.title !== item.question ? <p className="truncate text-small text-fg-muted">{item.question}</p> : null}
          </div>
          <Menu>
            <MenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t("common.more")}>
                <Ellipsis />
              </Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem asChild>
                <Link to={`/?run=${item.run_id}`}>
                  <ExternalLink />
                  {t("common.open")}
                </Link>
              </MenuItem>
              {dashboard.editable ? (
                <>
                  <MenuItem disabled={index === 0} onSelect={() => { onMove(index, index - 1); }}>
                    <ArrowUp />
                    {t("dashboards.moveUp")}
                  </MenuItem>
                  <MenuItem disabled={index === dashboard.items.length - 1} onSelect={() => { onMove(index, index + 1); }}>
                    <ArrowDown />
                    {t("dashboards.moveDown")}
                  </MenuItem>
                  <MenuSeparator />
                  <MenuItem onSelect={() => { unpin.mutate(); }} className="text-danger data-[highlighted]:text-danger">
                    <PinOff />
                    {t("dashboards.unpin")}
                  </MenuItem>
                </>
              ) : null}
            </MenuContent>
          </Menu>
        </header>
        <div className="flex-1 p-4">
          {!result ? (
            <p className="text-small text-fg-muted">{t("dashboards.missingStep")}</p>
          ) : chart && isChartable(chart) ? (
            <LazyChartView spec={chart} title={item.title} height={260} />
          ) : chart?.kind === "kpi" ? (
            <KpiCards kpis={chart.kpis} />
          ) : (
            <DataTable columns={result.columns} rows={result.rows} title={item.title} maxHeight={260} truncated={result.truncated} />
          )}
        </div>
      </article>
    </li>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { id = "" } = useParams();
  const board = useQuery({ queryKey: ["dashboard", id], queryFn: () => endpoints.getDashboard(api, id) });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["dashboard", id] });
    void queryClient.invalidateQueries({ queryKey: ["dashboards"] });
  };
  const share = useMutation({
    mutationFn: (shared: boolean) => endpoints.updateDashboard(api, id, { shared }),
    onSuccess: invalidate,
    onError: (error) => toast.error(errorMessage(error, t)),
  });
  const remove = useMutation({
    mutationFn: () => endpoints.deleteDashboard(api, id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboards"] });
      void navigate("/dashboards");
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => endpoints.reorderItems(api, id, ids),
    onSuccess: (data) => {
      queryClient.setQueryData(["dashboard", id], data);
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });

  const back = (
    <Button asChild variant="ghost" size="sm" className="-ml-2 w-fit">
      <Link to="/dashboards">
        <ArrowLeft />
        {t("dashboards.title")}
      </Link>
    </Button>
  );

  if (board.isPending) {
    return (
      <Page>
        {back}
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </Page>
    );
  }
  if (board.isError) {
    return (
      <Page>
        {back}
        <ErrorState error={board.error} onRetry={() => void board.refetch()} />
      </Page>
    );
  }
  const data = board.data;
  const move = (from: number, to: number) => {
    const ids = data.items.map((item) => item.id);
    const [moved] = ids.splice(from, 1);
    if (moved === undefined) return;
    ids.splice(to, 0, moved);
    reorder.mutate(ids);
  };

  return (
    <Page>
      {back}
      <PageHeader
        title={data.name}
        subtitle={data.editable ? t("dashboards.items", { count: data.items.length }) : `${t("dashboards.owner", { name: data.owner_name })} · ${t("dashboards.readOnly")}`}
        actions={
          data.editable ? (
            <>
              <label className="flex items-center gap-2 text-small text-fg-secondary">
                <Switch checked={data.shared} disabled={share.isPending} onCheckedChange={(value) => { share.mutate(value); }} />
                {t("dashboards.shared")}
              </label>
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="danger" size="sm">
                    <Trash2 />
                    {t("common.delete")}
                  </Button>
                </DialogTrigger>
                <DialogContent title={t("dashboards.deleteTitle", { name: data.name })} description={t("dashboards.deleteBody")}>
                  <div className="flex justify-end gap-2">
                    <Button variant="danger" disabled={remove.isPending} onClick={() => { remove.mutate(); }}>
                      <Trash2 />
                      {t("common.delete")}
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>
            </>
          ) : null
        }
      />
      {data.items.length === 0 ? (
        <EmptyState
          icon={LayoutDashboard}
          title={t("dashboards.emptyBoard")}
          action={
            <Button asChild variant="secondary">
              <Link to="/">{t("dashboards.goToWorkspace")}</Link>
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-4 lg:grid-cols-3">
          {data.items.map((item, index) => (
            <ItemCard key={item.id} item={item} dashboard={data} index={index} onMove={move} />
          ))}
        </ul>
      )}
    </Page>
  );
}
