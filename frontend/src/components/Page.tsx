import { RotateCcw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "../lib/cn";
import { errorMessage } from "../lib/errors";
import { Button } from "./ui/button";

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-6 px-4 py-6 sm:px-6 sm:py-8", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="grid min-w-0 gap-1">
        <h1 className="text-h1 text-fg">{title}</h1>
        {subtitle ? <p className="max-w-2xl text-fg-secondary">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  className,
}: {
  icon: LucideIcon;
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-3 rounded-xl border border-dashed border-line-strong px-6 py-14 text-center", className)}>
      <span className="flex size-11 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-fg-muted">
        <Icon aria-hidden="true" className="size-5" />
      </span>
      <p className="font-display text-h2 text-fg">{title}</p>
      {body ? <p className="max-w-md text-fg-secondary">{body}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger/40 bg-danger-soft px-4 py-3">
      <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-danger" />
      <p className="flex-1 text-small text-fg">{errorMessage(error, t)}</p>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          <RotateCcw />
          {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}
