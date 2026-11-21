import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Monitor, Moon, Sun } from "lucide-react";
import { useId, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import type { Preferences } from "../../api/types";
import { useApi, useAuth } from "../../app/auth";
import { usePreferences, type ThemePreference } from "../../app/preferences";
import { ErrorState, Page, PageHeader } from "../../components/Page";
import { Switch } from "../../components/ui/overlays";
import { Badge, Kbd, Panel, Skeleton } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import type { AppLocale } from "../../lib/format";

function Row({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
      <label htmlFor={htmlFor} className="grid gap-0.5">
        <span className="text-fg">{label}</span>
        {hint ? <span className="text-small text-fg-muted">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; icon?: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-md border border-line-strong bg-surface-2 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => {
            onChange(option.value);
          }}
          className={cn(
            "flex h-8 items-center gap-1.5 rounded-sm px-3 text-small transition-colors [&_svg]:size-4",
            value === option.value ? "bg-surface-3 text-fg shadow-sm" : "text-fg-muted hover:text-fg",
          )}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const api = useApi();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  const ids = { chart: useId(), sql: useId() };
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => endpoints.getPreferences(api) });

  const save = useMutation({
    mutationFn: (patch: Preferences) => endpoints.savePreferences(api, patch),
    onSuccess: (data) => {
      queryClient.setQueryData(["preferences"], data);
      toast.success(t("settings.saved"));
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });

  const changeLocale = (next: AppLocale) => {
    setLocale(next);
    // The agent writes its answers in the stored language.
    save.mutate({ locale: next });
  };

  const shortcuts: { keys: string[]; label: string }[] = [
    { keys: ["Ctrl", "K"], label: t("settings.keys.palette") },
    { keys: ["/"], label: t("settings.keys.focus") },
    { keys: ["Enter"], label: t("settings.keys.ask") },
    { keys: ["Shift", "Enter"], label: t("settings.keys.newline") },
  ];

  return (
    <Page className="max-w-3xl">
      <PageHeader title={t("settings.title")} />

      <Panel aria-labelledby="appearance">
        <h2 id="appearance" className="border-b border-line px-4 py-3 text-h3 text-fg">
          {t("settings.appearance")}
        </h2>
        <div className="divide-y divide-line">
          <Row label={t("settings.theme")}>
            <Segmented<ThemePreference>
              label={t("settings.theme")}
              value={theme}
              onChange={setTheme}
              options={[
                { value: "dark", label: t("theme.dark"), icon: <Moon aria-hidden="true" /> },
                { value: "light", label: t("theme.light"), icon: <Sun aria-hidden="true" /> },
                { value: "system", label: t("theme.system"), icon: <Monitor aria-hidden="true" /> },
              ]}
            />
          </Row>
          <Row label={t("settings.language")} hint={t("settings.languageHint")}>
            <Segmented<AppLocale>
              label={t("settings.language")}
              value={locale}
              onChange={changeLocale}
              options={[
                { value: "es", label: t("language.es") },
                { value: "en", label: t("language.en") },
              ]}
            />
          </Row>
        </div>
      </Panel>

      <Panel aria-labelledby="answers">
        <h2 id="answers" className="border-b border-line px-4 py-3 text-h3 text-fg">
          {t("settings.answers")}
        </h2>
        {preferences.isPending ? (
          <div className="grid gap-2 p-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : preferences.isError ? (
          <div className="p-4">
            <ErrorState error={preferences.error} onRetry={() => void preferences.refetch()} />
          </div>
        ) : (
          <div className="divide-y divide-line">
            <Row label={t("settings.defaultChart")} htmlFor={ids.chart}>
              <select
                id={ids.chart}
                value={preferences.data.default_chart ?? "auto"}
                onChange={(event) => {
                  save.mutate({ default_chart: event.target.value as NonNullable<Preferences["default_chart"]> });
                }}
                className="h-9 rounded-md border border-line-strong bg-surface-2 px-3 text-fg"
              >
                {(["auto", "bar", "line", "pie", "table"] as const).map((value) => (
                  <option key={value} value={value}>
                    {t(`settings.charts.${value}`)}
                  </option>
                ))}
              </select>
            </Row>
            <Row label={t("settings.showSql")} htmlFor={ids.sql}>
              <Switch
                id={ids.sql}
                checked={preferences.data.show_sql ?? false}
                onCheckedChange={(checked) => {
                  save.mutate({ show_sql: checked });
                }}
              />
            </Row>
          </div>
        )}
      </Panel>

      {user ? (
        <Panel aria-labelledby="account">
          <h2 id="account" className="border-b border-line px-4 py-3 text-h3 text-fg">
            {t("settings.account")}
          </h2>
          <dl className="grid gap-4 p-4 sm:grid-cols-3">
            <div className="grid gap-0.5">
              <dt className="label-micro">{t("settings.name")}</dt>
              <dd className="text-fg">{user.display_name}</dd>
            </div>
            <div className="grid min-w-0 gap-0.5">
              <dt className="label-micro">{t("settings.email")}</dt>
              <dd className="truncate text-fg">{user.email}</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="label-micro">{t("settings.role")}</dt>
              <dd>
                <Badge tone="accent">{t(`roles.${user.role}`)}</Badge>
              </dd>
            </div>
          </dl>
        </Panel>
      ) : null}

      <Panel aria-labelledby="shortcuts">
        <h2 id="shortcuts" className="border-b border-line px-4 py-3 text-h3 text-fg">
          {t("settings.shortcuts")}
        </h2>
        <ul className="divide-y divide-line">
          {shortcuts.map((s) => (
            <li key={s.label} className="flex items-center justify-between gap-3 px-4 py-3">
              <span className="text-fg-secondary">{s.label}</span>
              <span className="flex items-center gap-1">
                {s.keys.map((key) => (
                  <Kbd key={key}>{key}</Kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Panel>
    </Page>
  );
}
