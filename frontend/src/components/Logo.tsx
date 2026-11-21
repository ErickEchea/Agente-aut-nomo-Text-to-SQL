import { useTranslation } from "react-i18next";

import { cn } from "../lib/cn";

/** Brand mark: three nodes on a path (question → schema → answer). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)}>
      <rect width="32" height="32" rx="8" className="fill-surface-3" />
      <path d="M9 22 L16 10 L23 22" fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="stroke-accent" />
      <circle cx="9" cy="22" r="3" strokeWidth="2" className="fill-surface-3 stroke-accent" />
      <circle cx="16" cy="10" r="3" className="fill-accent" />
      <circle cx="23" cy="22" r="3" strokeWidth="2" className="fill-surface-3 stroke-accent" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="font-display text-[1.0625rem] font-semibold tracking-[0.06em] text-fg">
        {t("app.brand")}
        <span className="text-accent"> {t("app.brandSuffix")}</span>
      </span>
    </span>
  );
}
