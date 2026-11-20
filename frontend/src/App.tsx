import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { fetchReadiness } from "./api/health";
import type { Locale } from "./i18n/resources";

const POLL_MS = 10_000;
const KNOWN_CHECKS = ["app_db", "demo_db", "ollama"] as const;

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.length > 0 ? value.map(String).join(", ") : "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function describeDetail(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(" · ");
}

export function App() {
  const { t, i18n } = useTranslation();
  const readiness = useQuery({
    queryKey: ["health", "ready"],
    queryFn: ({ signal }) => fetchReadiness(signal),
    refetchInterval: POLL_MS,
    retry: false,
  });

  const setLocale = (locale: Locale) => {
    void i18n.changeLanguage(locale);
    document.documentElement.lang = locale;
  };

  return (
    <div className="shell">
      <header className="shell__header">
        <div>
          <h1 className="brand">
            NEXUS<span className="brand__accent"> AI</span>
          </h1>
          <p className="muted">{t("app.tagline")}</p>
        </div>
        <select
          value={i18n.resolvedLanguage}
          onChange={(event) => {
            setLocale(event.target.value as Locale);
          }}
          aria-label={t("language.label")}
        >
          <option value="es">{t("language.es")}</option>
          <option value="en">{t("language.en")}</option>
        </select>
      </header>

      <main className="panel" aria-live="polite">
        <h2>{t("status.title")}</h2>
        <p className="muted">{t("status.subtitle")}</p>

        {readiness.isPending && <p role="status">{t("status.loading")}</p>}

        {readiness.isError && (
          <div className="alert" role="alert">
            <p>{t("status.unreachable")}</p>
            <button type="button" onClick={() => void readiness.refetch()}>
              {t("status.retry")}
            </button>
          </div>
        )}

        {readiness.isSuccess && (
          <>
            <p className={`badge badge--${readiness.data.status === "ready" ? "ok" : "fail"}`}>
              {readiness.data.status === "ready" ? t("status.ready") : t("status.notReady")}
            </p>
            <ul className="checks">
              {KNOWN_CHECKS.map((name) => {
                const check = readiness.data.checks[name];
                if (!check) return null;
                return (
                  <li key={name} className="check">
                    <span className={`dot dot--${check.ok ? "ok" : "fail"}`} aria-hidden="true" />
                    <div className="check__body">
                      <div className="check__title">
                        <strong>{t(`status.checks.${name}`)}</strong>
                        <span className="mono">
                          {check.ok ? t("status.ok") : t("status.failed")} ·{" "}
                          {t("status.latency", { ms: Math.round(check.latency_ms) })}
                        </span>
                      </div>
                      <p className="mono muted small">{describeDetail(check.detail)}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="muted small">
              {t("status.version", { version: readiness.data.version })} ·{" "}
              {t("status.lastChecked", {
                time: new Date(readiness.dataUpdatedAt).toLocaleTimeString(i18n.resolvedLanguage),
              })}
            </p>
          </>
        )}
      </main>
    </div>
  );
}
