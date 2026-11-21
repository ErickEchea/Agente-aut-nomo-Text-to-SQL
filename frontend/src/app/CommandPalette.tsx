/** Ctrl/⌘ K: ask the agent, jump to a screen, reopen a recent query or run an action. */
import { useQuery } from "@tanstack/react-query";
import { Command, defaultFilter } from "cmdk";
import { Dialog as D } from "radix-ui";
import { CornerDownLeft, Languages, LogOut, MessageSquarePlus, Moon, Search, Sparkles, Sun, History } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import * as endpoints from "../api/endpoints";
import { useWorkspace } from "../features/workspace/session";
import { errorMessage } from "../lib/errors";
import { useApi, useAuth, useCan } from "./auth";
import { NAV } from "./nav";
import { usePreferences } from "./preferences";

function Item({ children, onSelect, value, icon }: { children: ReactNode; onSelect: () => void; value: string; icon: ReactNode }) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-body text-fg-secondary data-[selected=true]:bg-surface-3 data-[selected=true]:text-fg [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-fg-muted"
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </Command.Item>
  );
}

// "Ask the agent" always ranks below real matches, so typing a screen name + Enter navigates.
const ASK = "ask ";
const filter = (value: string, search: string, keywords?: string[]) =>
  value.startsWith(ASK) ? 0.0001 : defaultFilter(value, search, keywords);

const group = "[&_[cmdk-group-heading]]:label-micro [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1";

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const api = useApi();
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { admin } = useCan();
  const { resolvedTheme, setTheme, locale, setLocale } = usePreferences();
  const { ask, newConversation } = useWorkspace();
  const [query, setQuery] = useState("");

  const recent = useQuery({ queryKey: ["runs"], queryFn: () => endpoints.listRuns(api, 50), enabled: open });

  const setOpen = (next: boolean) => {
    if (!next) setQuery("");
    onOpenChange(next);
  };

  const run = (action: () => void) => {
    setOpen(false);
    action();
  };

  const askAgent = (question: string) => {
    run(() => {
      void navigate("/");
      ask(question).catch((error: unknown) => toast.error(errorMessage(error, t)));
    });
  };

  const examples = t("examples", { returnObjects: true }) as unknown as string[];
  const trimmed = query.trim();

  return (
    <D.Root open={open} onOpenChange={setOpen}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-scrim backdrop-blur-[2px]" />
        <D.Content
          aria-describedby={undefined}
          className="fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-line bg-surface-1 shadow-overlay"
        >
          <D.Title className="sr-only">{t("palette.label")}</D.Title>
          <Command label={t("palette.label")} loop filter={filter}>
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search aria-hidden="true" className="size-4 text-fg-muted" />
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder={t("palette.placeholder")}
                className="h-12 flex-1 bg-transparent text-[0.9375rem] text-fg placeholder:text-fg-muted focus:outline-none"
                onKeyDown={(event) => {
                  // Enter with no match asks the agent directly.
                  if (event.key === "Enter" && trimmed.length >= 3 && !document.querySelector("[cmdk-item][data-selected=true]")) {
                    event.preventDefault();
                    askAgent(trimmed);
                  }
                }}
              />
            </div>
            <Command.List className="max-h-[60vh] overflow-y-auto p-1.5">
              <Command.Empty className="px-3 py-6 text-center text-small text-fg-muted">{t("palette.empty")}</Command.Empty>
              <Command.Group heading={t("palette.navigate")} className={group}>
                {NAV.filter((item) => !item.adminOnly || admin).map((item) => (
                  <Item key={item.to} value={`nav ${t(`nav.${item.key}`)}`} icon={<item.icon />} onSelect={() => { run(() => void navigate(item.to)); }}>
                    {t(`nav.${item.key}`)}
                  </Item>
                ))}
              </Command.Group>
              <Command.Group heading={t("palette.actions")} className={group}>
                <Item value="action new conversation" icon={<MessageSquarePlus />} onSelect={() => { run(() => { newConversation(); void navigate("/"); }); }}>
                  {t("palette.newConversation")}
                </Item>
                <Item value="action theme" icon={resolvedTheme === "dark" ? <Sun /> : <Moon />} onSelect={() => { run(() => { setTheme(resolvedTheme === "dark" ? "light" : "dark"); }); }}>
                  {t("palette.toggleTheme")}
                </Item>
                <Item value="action language" icon={<Languages />} onSelect={() => { run(() => { setLocale(locale === "es" ? "en" : "es"); }); }}>
                  {t("palette.switchLanguage")}
                </Item>
                <Item value="action sign out" icon={<LogOut />} onSelect={() => { run(() => void signOut()); }}>
                  {t("palette.signOut")}
                </Item>
              </Command.Group>
              {recent.data && recent.data.length > 0 ? (
                <Command.Group heading={t("palette.recent")} className={group}>
                  {recent.data.slice(0, 8).map((r) => (
                    <Item key={r.id} value={`recent ${r.id} ${r.question}`} icon={<History />} onSelect={() => { run(() => void navigate(`/?run=${r.id}`)); }}>
                      {r.question}
                    </Item>
                  ))}
                </Command.Group>
              ) : null}
              <Command.Group heading={t("palette.examples")} className={group}>
                {examples.map((example) => (
                  <Item key={example} value={`example ${example}`} icon={<CornerDownLeft />} onSelect={() => { askAgent(example); }}>
                    {example}
                  </Item>
                ))}
              </Command.Group>
              {trimmed.length >= 3 ? (
                <Command.Group heading={t("palette.actions")} className={group}>
                  <Item value={`${ASK}${trimmed}`} icon={<Sparkles />} onSelect={() => { askAgent(trimmed); }}>
                    {t("palette.askAgent", { query: trimmed })}
                  </Item>
                </Command.Group>
              ) : null}
            </Command.List>
          </Command>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
