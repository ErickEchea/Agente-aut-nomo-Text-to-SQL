import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Database, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import * as endpoints from "../../api/endpoints";
import type { ConnectionSummary } from "../../api/types";
import { useApi } from "../../app/auth";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger, Tooltip } from "../../components/ui/overlays";
import { useWorkspace } from "./session";

/** The registered sources and the one the workspace is (or will be) asking. */
export function useSources(): { sources: ConnectionSummary[]; active: ConnectionSummary | undefined } {
  const api = useApi();
  const { conversationSource, selectedSource, turns } = useWorkspace();
  const list = useQuery({ queryKey: ["connections"], queryFn: () => endpoints.listConnections(api), staleTime: 60_000 });
  const sources = list.data ?? [];
  const wanted = turns.length > 0 ? conversationSource : selectedSource;
  const active = sources.find((s) => s.key === wanted) ?? sources.find((s) => s.builtin);
  return { sources, active };
}

export function SourcePicker() {
  const { t } = useTranslation();
  const { turns, setSelectedSource } = useWorkspace();
  const { sources, active } = useSources();
  if (!active) return null;
  const label = (
    <>
      <Database aria-hidden="true" className="size-3.5 text-accent" />
      <span className="max-w-40 truncate">{active.name}</span>
    </>
  );
  const chip =
    "inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-2 text-small text-fg-secondary";

  if (turns.length > 0 || sources.length < 2) {
    return (
      <Tooltip content={turns.length > 0 ? t("workspace.sourceLocked", { name: active.name }) : t("workspace.source")}>
        <span className={chip} tabIndex={0}>
          {label}
          {turns.length > 0 ? <Lock aria-hidden="true" className="size-3 text-fg-muted" /> : null}
        </span>
      </Tooltip>
    );
  }
  return (
    <Menu>
      <MenuTrigger asChild>
        <button type="button" className={`${chip} hover:border-line-strong hover:text-fg`} aria-label={`${t("workspace.source")}: ${active.name}`}>
          {label}
          <ChevronDown aria-hidden="true" className="size-3.5 text-fg-muted" />
        </button>
      </MenuTrigger>
      <MenuContent align="start" className="w-72">
        <MenuLabel>{t("workspace.source")}</MenuLabel>
        {sources.map((source) => (
          <MenuItem
            key={source.key}
            onSelect={() => {
              setSelectedSource(source.key);
            }}
          >
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-fg">{source.name}</span>
              <span className="label-micro normal-case tracking-normal">
                {source.engine} · {source.database}
              </span>
            </span>
            {source.key === active.key ? <Check className="text-accent" /> : null}
          </MenuItem>
        ))}
      </MenuContent>
    </Menu>
  );
}
