/** Virtualized results grid: sorting, a global filter and CSV export (TanStack Table v9 + Virtual). */
import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, FileDown, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { JsonScalar } from "../../api/types";
import { usePreferences } from "../../app/preferences";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { downloadBlob, safeFilename, toCsv } from "../../lib/csv";
import { formatCell, kindForColumn, type ValueKind } from "../../lib/format";

type Row = JsonScalar[];

const features = tableFeatures({
  rowSortingFeature,
  columnFilteringFeature,
  globalFilteringFeature,
  sortedRowModel: createSortedRowModel(),
  filteredRowModel: createFilteredRowModel(),
  sortFns: { basic: sortFn_basic, alphanumeric: sortFn_alphanumeric },
  filterFns: { includesString: filterFn_includesString },
});

const helper = createColumnHelper<typeof features, Row>();
const ROW_HEIGHT = 36;

interface DataTableProps {
  columns: string[];
  rows: Row[];
  title: string;
  truncated?: boolean;
  maxHeight?: number;
}

export function DataTable({ columns, rows, title, truncated = false, maxHeight = 420 }: DataTableProps) {
  const { t } = useTranslation();
  const { locale } = usePreferences();
  const [filter, setFilter] = useState("");

  const kinds = useMemo<ValueKind[]>(
    () => columns.map((name, i) => kindForColumn(name, rows.slice(0, 50).map((r) => r[i]))),
    [columns, rows],
  );
  const numericColumns = useMemo(
    () => columns.map((_, i) => rows.some((r) => typeof r[i] === "number")),
    [columns, rows],
  );

  const columnDefs = useMemo(
    () =>
      columns.map((name, i) =>
        helper.accessor((row): unknown => row[i] ?? null, {
          id: `c${i}`,
          header: name,
          sortFn: numericColumns[i] ? "basic" : "alphanumeric",
          sortUndefined: "last",
          cell: (info) => formatCell(info.getValue(), locale, kinds[i] ?? "number"),
        }),
      ),
    [columns, kinds, numericColumns, locale],
  );

  const table = useTable({
    features,
    columns: columnDefs,
    data: rows,
    state: { globalFilter: filter },
    onGlobalFilterChange: setFilter,
    globalFilterFn: "includesString",
  });

  const visible = table.getRowModel().rows;
  const scroller = useRef<HTMLDivElement>(null);
  // TanStack Virtual returns fresh functions each render; this app does not use the React Compiler.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  const exportCsv = () => {
    const data = visible.map((row) => row.original);
    downloadBlob(new Blob([toCsv(columns, data)], { type: "text/csv;charset=utf-8" }), safeFilename(title, "csv"));
  };

  if (rows.length === 0) {
    return <p className="px-1 py-6 text-center text-fg-muted">{t("results.noRows")}</p>;
  }

  const items = virtualizer.getVirtualItems();
  const padTop = items[0]?.start ?? 0;
  const padBottom = virtualizer.getTotalSize() - (items.at(-1)?.end ?? 0);
  // Text gets room to breathe; identifiers stay narrow; figures align right in compact columns.
  const template = columns
    .map((_, i) =>
      kinds[i] === "id" ? "minmax(5.5rem, 0.6fr)" : numericColumns[i] ? "minmax(7.5rem, 1fr)" : "minmax(12rem, 2fr)",
    )
    .join(" ");

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-48 flex-1 sm:max-w-xs">
          <span className="sr-only">{t("results.filter")}</span>
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-fg-muted" />
          <Input
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value);
            }}
            placeholder={t("results.filter")}
            className="h-9 pl-8"
          />
        </label>
        <span className="label-micro" aria-live="polite">
          {filter
            ? t("results.filtered", { shown: visible.length, total: rows.length })
            : t("results.rows", { count: rows.length })}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={exportCsv}>
          <FileDown />
          {t("results.exportCsv")}
        </Button>
      </div>

      <div
        ref={scroller}
        className="overflow-auto rounded-md border border-line"
        style={{ maxHeight }}
        role="region"
        aria-label={title}
        tabIndex={0}
      >
        <table className="w-full border-collapse text-small" style={{ display: "grid" }}>
          <thead className="sticky top-0 z-10 bg-surface-2" style={{ display: "grid" }}>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} style={{ display: "grid", gridTemplateColumns: template }}>
                {group.headers.map((header, i) => {
                  const sorted = header.column.getIsSorted();
                  const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      className="border-b border-line p-0 text-left font-medium"
                    >
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "flex h-9 w-full items-center gap-1.5 px-3 text-fg-secondary hover:text-fg",
                          numericColumns[i] && "justify-end",
                        )}
                      >
                        <span className="truncate">{String(header.column.columnDef.header)}</span>
                        <Icon aria-hidden="true" className={cn("size-3.5 shrink-0", sorted ? "text-accent" : "opacity-40")} />
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody style={{ display: "grid" }}>
            {padTop > 0 ? <tr style={{ height: padTop }} aria-hidden="true" /> : null}
            {items.map((item) => {
              const row = visible[item.index];
              if (!row) return null;
              return (
                <tr
                  key={row.id}
                  style={{ display: "grid", gridTemplateColumns: template, height: ROW_HEIGHT }}
                  className="border-b border-line/60 hover:bg-surface-3/60"
                >
                  {row.getAllCells().map((cell, i) => (
                    <td
                      key={cell.id}
                      title={numericColumns[i] ? undefined : formatCell(cell.getValue(), locale, kinds[i] ?? "number")}
                      className={cn(
                        "truncate px-3 leading-[36px] text-fg",
                        numericColumns[i] && "figures text-right",
                      )}
                    >
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              );
            })}
            {padBottom > 0 ? <tr style={{ height: padBottom }} aria-hidden="true" /> : null}
          </tbody>
        </table>
      </div>
      {truncated ? <p className="text-small text-warning">{t("results.truncated", { count: rows.length })}</p> : null}
    </div>
  );
}
