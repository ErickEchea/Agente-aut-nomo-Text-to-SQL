import { Check, Copy } from "lucide-react";
import type { ThemedToken } from "shiki/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "../../components/ui/button";
import { cn } from "../../lib/cn";
import { layoutSql, lineDiff } from "../../lib/diff";
import { tokenizeSql } from "../../lib/highlight";

function useTokens(code: string): ThemedToken[][] | null {
  const [tokens, setTokens] = useState<{ code: string; lines: ThemedToken[][] } | null>(null);
  useEffect(() => {
    let alive = true;
    tokenizeSql(code)
      .then((lines) => {
        if (alive) setTokens({ code, lines });
      })
      .catch(() => {
        // Highlighting is progressive enhancement: plain text stays visible.
      });
    return () => {
      alive = false;
    };
  }, [code]);
  return tokens?.code === code ? tokens.lines : null;
}

function Line({ tokens, fallback }: { tokens: ThemedToken[] | undefined; fallback: string }) {
  if (!tokens) return <>{fallback || " "}</>;
  if (tokens.length === 0) return <> </>;
  return (
    <>
      {tokens.map((token, i) => (
        <span
          key={i}
          style={{
            color: token.color,
            fontStyle: token.fontStyle !== undefined && token.fontStyle & 1 ? "italic" : undefined,
          }}
        >
          {token.content}
        </span>
      ))}
    </>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 1500);
    });
  };
  return (
    <Button variant="ghost" size="sm" onClick={copy} aria-live="polite">
      {copied ? <Check /> : <Copy />}
      {copied ? t("common.copied") : (label ?? t("common.copy"))}
    </Button>
  );
}

export function SqlBlock({
  sql,
  className,
  copyable = true,
  compact = false,
}: {
  sql: string;
  className?: string;
  copyable?: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const code = layoutSql(sql);
  const tokens = useTokens(code);
  const lines = code.split("\n");
  return (
    <div className={cn("relative min-w-0 rounded-md border border-line bg-surface-2", className)}>
      {copyable ? (
        <div className="flex items-center justify-between gap-2 border-b border-line py-1 pr-1 pl-4">
          <span className="label-micro">{t("results.dialect")}</span>
          <CopyButton text={sql} label={t("results.copySql")} />
        </div>
      ) : null}
      <pre className={cn("sql-code overflow-x-auto", compact ? "p-2.5 text-[0.75rem]" : "p-4")}>
        <code>
          {lines.map((line, i) => (
            <div key={i} className="flex">
              {!compact ? (
                <span aria-hidden="true" className="mr-4 w-6 shrink-0 text-right text-fg-muted/70 select-none">
                  {i + 1}
                </span>
              ) : null}
              <span className="whitespace-pre">
                <Line tokens={tokens?.[i]} fallback={line} />
              </span>
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}

/** Unified red/green diff between two SQL attempts (repair view). */
export function SqlDiff({ before, after }: { before: string; after: string }) {
  const lines = lineDiff(before, after);
  return (
    <pre className="sql-code min-w-0 overflow-x-auto rounded-md border border-line bg-surface-2 py-2 text-[0.75rem]">
      <code>
        {lines.map((line, i) => (
          <div
            key={i}
            className={cn(
              "flex px-2",
              line.kind === "add" && "bg-success-soft",
              line.kind === "remove" && "bg-danger-soft",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "mr-2 w-3 shrink-0 select-none",
                line.kind === "add" ? "text-success" : line.kind === "remove" ? "text-danger" : "text-fg-muted",
              )}
            >
              {line.kind === "add" ? "+" : line.kind === "remove" ? "−" : " "}
            </span>
            <span className="sr-only">{line.kind === "add" ? "+" : line.kind === "remove" ? "-" : ""}</span>
            <span className={cn("whitespace-pre", line.kind === "remove" && "text-fg-secondary line-through decoration-danger/50")}>
              {line.text || " "}
            </span>
          </div>
        ))}
      </code>
    </pre>
  );
}
