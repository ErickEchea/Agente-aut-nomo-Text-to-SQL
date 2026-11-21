/** Locale-aware formatting. Money is USD (Ecuador); es → es-EC, en → en-US. */

export type AppLocale = "es" | "en";

const INTL_LOCALE: Record<AppLocale, string> = { es: "es-EC", en: "en-US" };

export function intlLocale(locale: string): string {
  return locale === "en" ? INTL_LOCALE.en : INTL_LOCALE.es;
}

// Column names that hold money in the retail schema and in typical aliases the agent produces.
const MONEY = /(ingreso|venta|monto|total|precio|costo|importe|valor|ticket|revenue|amount|price|cost|sales|usd|subtotal|descuento|iva)/i;
const COUNT = /(cantidad|unidades|numero|num_|conteo|count|qty|units|clientes|transacciones|filas)/i;
const PERCENT = /(porcentaje|pct|ratio|tasa|margen|participacion|share|percent)/i;
const ID = /(^id$|_id$|^codigo|^cedula|^ruc|^telefono|^anio$|^año$|^year$|^mes$|^month$)/i;

export type ValueKind = "money" | "percent" | "integer" | "number" | "id";

export function kindForColumn(column: string, sample: readonly unknown[]): ValueKind {
  const name = column.normalize("NFD").replace(/[̀-ͯ]/g, "");
  if (ID.test(name)) return "id";
  if (PERCENT.test(name)) return "percent";
  if (COUNT.test(name)) return "integer";
  if (MONEY.test(name)) return "money";
  const numbers = sample.filter((v): v is number => typeof v === "number");
  return numbers.length > 0 && numbers.every(Number.isInteger) ? "integer" : "number";
}

export function formatNumber(value: number, locale: string, kind: ValueKind = "number"): string {
  const loc = intlLocale(locale);
  switch (kind) {
    case "money":
      return new Intl.NumberFormat(loc, {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
    case "percent":
      // Values above 1 are already percentages (e.g. 12.5 → 12,5 %).
      return new Intl.NumberFormat(loc, { style: "percent", maximumFractionDigits: 1 }).format(
        Math.abs(value) > 1 ? value / 100 : value,
      );
    case "integer":
      return new Intl.NumberFormat(loc, { maximumFractionDigits: 0 }).format(value);
    case "id":
      return String(value);
    case "number":
      return new Intl.NumberFormat(loc, { maximumFractionDigits: 2 }).format(value);
  }
}

/** Compact figures for KPI cards and axes: 1,2 K · 299,7 K · 4,2 M. */
export function formatCompact(value: number, locale: string, kind: ValueKind = "number"): string {
  const loc = intlLocale(locale);
  if (Math.abs(value) < 10_000) return formatNumber(value, locale, kind);
  const options: Intl.NumberFormatOptions = { notation: "compact", maximumFractionDigits: 1 };
  if (kind === "money") Object.assign(options, { style: "currency", currency: "USD" });
  return new Intl.NumberFormat(loc, options).format(value);
}

export function formatCell(value: unknown, locale: string, kind: ValueKind): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value, locale, kind);
  if (typeof value === "boolean") return value ? "✓" : "✗";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function formatDuration(ms: number | null | undefined, locale: string): string {
  if (ms === null || ms === undefined) return "—";
  const loc = intlLocale(locale);
  if (ms < 1000) return `${new Intl.NumberFormat(loc, { maximumFractionDigits: 0 }).format(ms)} ms`;
  return `${new Intl.NumberFormat(loc, { maximumFractionDigits: 1 }).format(ms / 1000)} s`;
}

export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(intlLocale(locale), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function formatDate(iso: string, locale: string): string {
  // Date-only strings are calendar dates: format them in UTC so they never shift a day.
  return new Intl.DateTimeFormat(intlLocale(locale), { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso),
  );
}

export function formatRelative(iso: string, locale: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(intlLocale(locale), { numeric: "auto" });
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86_400), "day");
}

/** A half-open date range [start, end) shown with an inclusive end: 1 jul 2026 – 30 sep 2026. */
export function formatRange(start: string, endExclusive: string, locale: string): string {
  const end = new Date(`${endExclusive}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() - 1);
  return `${formatDate(start, locale)} – ${formatDate(end.toISOString().slice(0, 10), locale)}`;
}
