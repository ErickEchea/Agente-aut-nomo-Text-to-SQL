import { useQuery } from "@tanstack/react-query";
import { Dialog as D } from "radix-ui";
import { Check, Languages, LogOut, Menu as MenuIcon, Monitor, Moon, Search, Sun, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router";

import * as endpoints from "../api/endpoints";
import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
  Tooltip,
} from "../components/ui/overlays";
import { Badge, Kbd } from "../components/ui/primitives";
import { QUESTION_INPUT_ID } from "../features/workspace/QueryBar";
import { useSources } from "../features/workspace/SourcePicker";
import { cn } from "../lib/cn";
import { useApi, useAuth, useCan } from "./auth";
import { CommandPalette } from "./CommandPalette";
import { NAV } from "./nav";
import { usePreferences, type ThemePreference } from "./preferences";

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { admin } = useCan();
  return (
    <ul className="grid gap-0.5">
      {NAV.filter((item) => !item.adminOnly || admin).map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            end={item.to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "relative flex h-9 items-center gap-3 rounded-md px-3 text-body transition-colors",
                isActive ? "bg-surface-3 text-fg" : "text-fg-secondary hover:bg-surface-2 hover:text-fg",
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" /> : null}
                <item.icon aria-hidden="true" className={cn("size-4", isActive ? "text-accent" : "text-fg-muted")} />
                {t(`nav.${item.key}`)}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function Health() {
  const { t } = useTranslation();
  const api = useApi();
  const ready = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => endpoints.readiness(api, signal),
    refetchInterval: 30_000,
    retry: false,
  });
  const state = ready.isError ? "down" : ready.data?.status === "ready" ? "up" : ready.data ? "degraded" : "unknown";
  const label =
    state === "up" ? t("topbar.healthy") : state === "degraded" ? t("topbar.degraded") : state === "down" ? t("topbar.unreachable") : t("common.loading");
  return (
    <Tooltip content={label}>
      <span role="status" aria-label={label} className="flex size-8 items-center justify-center">
        <span
          className={cn(
            "size-2 rounded-full",
            state === "up" && "bg-success",
            state === "degraded" && "bg-warning",
            state === "down" && "bg-danger",
            state === "unknown" && "bg-fg-muted",
          )}
        />
      </span>
    </Tooltip>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { user, signOut } = useAuth();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  if (!user) return null;
  const initials = user.display_name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          type="button"
          className="flex size-8 items-center justify-center rounded-full border border-line-strong bg-surface-2 font-mono text-micro text-fg hover:border-accent"
        >
          <span aria-hidden="true">{initials}</span>
          <span className="sr-only">{t("topbar.account")}</span>
        </button>
      </MenuTrigger>
      <MenuContent className="w-60">
        <div className="px-2 py-1.5">
          <p className="truncate font-medium text-fg">{user.display_name}</p>
          <p className="truncate text-small text-fg-muted">{user.email}</p>
          <Badge tone="accent" className="mt-1.5">
            {t(`roles.${user.role}`)}
          </Badge>
        </div>
        <MenuSeparator />
        <MenuLabel>{t("topbar.theme")}</MenuLabel>
        <MenuRadioGroup value={theme} onValueChange={(value) => { setTheme(value as ThemePreference); }}>
          {(["dark", "light", "system"] as const).map((value) => (
            <MenuRadioItem key={value} value={value}>
              {value === "dark" ? <Moon className="size-4" /> : value === "light" ? <Sun className="size-4" /> : <Monitor className="size-4" />}
              {t(`theme.${value}`)}
            </MenuRadioItem>
          ))}
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuLabel>{t("topbar.language")}</MenuLabel>
        {(["es", "en"] as const).map((value) => (
          <MenuItem key={value} onSelect={() => { setLocale(value); }}>
            <Languages />
            <span className="flex-1">{t(`language.${value}`)}</span>
            {locale === value ? <Check className="text-accent" /> : null}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem onSelect={() => void signOut()}>
          <LogOut />
          {t("topbar.signOut")}
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const location = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const source = useSources().active;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
      const target = event.target as HTMLElement | null;
      const typing = target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if (event.key === "/" && !typing && location.pathname === "/") {
        event.preventDefault();
        document.getElementById(QUESTION_INPUT_ID)?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [location.pathname]);

  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <div className="canvas-grid flex h-dvh overflow-hidden">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-accent px-3 py-2 text-accent-ink focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        {t("nav.skipToContent")}
      </a>

      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface-1 md:flex">
        <div className="flex h-14 items-center px-4">
          <Logo />
        </div>
        <nav aria-label={t("nav.label")} className="flex-1 overflow-y-auto px-2 py-3">
          <NavList />
        </nav>
        <p className="border-t border-line px-4 py-3 text-micro text-fg-muted">{t("app.tagline")}</p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface-1/80 px-3 backdrop-blur sm:px-4">
          <D.Root open={menuOpen} onOpenChange={setMenuOpen}>
            <D.Trigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label={t("nav.openMenu")}>
                <MenuIcon />
              </Button>
            </D.Trigger>
            <D.Portal>
              <D.Overlay className="fixed inset-0 z-40 bg-scrim md:hidden" />
              <D.Content
                aria-describedby={undefined}
                className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-line bg-surface-1 shadow-overlay data-[state=open]:animate-[fade-in_var(--duration-base)_ease-out] md:hidden"
              >
                <div className="flex h-14 items-center justify-between px-4">
                  <D.Title asChild>
                    <span>
                      <Logo />
                    </span>
                  </D.Title>
                  <D.Close asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={t("common.close")}>
                      <X />
                    </Button>
                  </D.Close>
                </div>
                <nav aria-label={t("nav.label")} className="flex-1 overflow-y-auto px-2 py-3">
                  <NavList onNavigate={() => { setMenuOpen(false); }} />
                </nav>
              </D.Content>
            </D.Portal>
          </D.Root>
          <span className="md:hidden">
            <Logo className="[&_svg]:size-7" />
          </span>

          <button
            type="button"
            onClick={() => {
              setPaletteOpen(true);
            }}
            className="ml-auto flex h-9 items-center gap-2 rounded-md border border-line-strong bg-surface-2 px-2.5 text-small text-fg-muted transition-colors hover:border-fg-muted hover:text-fg-secondary md:ml-0 md:w-72"
            aria-keyshortcuts="Control+K Meta+K"
          >
            <Search aria-hidden="true" className="size-4" />
            <span className="hidden flex-1 text-left md:inline">{t("topbar.search")}</span>
            <span className="hidden items-center gap-0.5 md:flex">
              <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
              <Kbd>K</Kbd>
            </span>
            <span className="sr-only md:hidden">{t("topbar.search")}</span>
          </button>

          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            {source ? (
              <Badge tone={source.read_only ? "neutral" : "warning"} className="hidden lg:inline-flex">
                <span aria-hidden="true" className={cn("size-1.5 rounded-full", source.read_only ? "bg-success" : "bg-warning")} />
                {t("topbar.connection", { key: source.key })}
              </Badge>
            ) : null}
            <Health />
            <UserMenu />
          </div>
        </header>

        {/* Focusable so keyboard users can scroll long pages; it is also the skip-link target. */}
        <main
          id="main"
          tabIndex={0}
          className="flex min-h-0 flex-1 flex-col overflow-y-auto outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-inset"
        >
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
