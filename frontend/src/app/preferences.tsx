/** Theme (dark default, light, system) and language, persisted per browser; language also on the server. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AppLocale } from "../lib/format";

export type ThemePreference = "dark" | "light" | "system";
type ResolvedTheme = "dark" | "light";

const THEME_KEY = "nexus.theme";
const LOCALE_KEY = "nexus.locale";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage blocked (private mode): the preference just lasts for this session.
  }
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

interface PreferencesValue {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

export function initialLocale(): AppLocale {
  return readStorage(LOCALE_KEY) === "en" ? "en" : "es";
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  const [theme, setThemeState] = useState<ThemePreference>(() => {
    const stored = readStorage(THEME_KEY);
    return stored === "light" || stored === "system" ? stored : "dark";
  });
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme);
  const resolvedTheme = theme === "system" ? system : theme;

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      setSystem(query.matches ? "light" : "dark");
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset["theme"] = resolvedTheme;
  }, [resolvedTheme]);

  const setTheme = useCallback((next: ThemePreference) => {
    writeStorage(THEME_KEY, next);
    setThemeState(next);
  }, []);

  const locale: AppLocale = i18n.resolvedLanguage === "en" ? "en" : "es";

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    (next: AppLocale) => {
      writeStorage(LOCALE_KEY, next);
      void i18n.changeLanguage(next);
    },
    [i18n],
  );

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, locale, setLocale }),
    [theme, resolvedTheme, setTheme, locale, setLocale],
  );
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences must be used inside <PreferencesProvider>");
  return value;
}
