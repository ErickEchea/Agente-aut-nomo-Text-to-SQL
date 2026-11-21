/** Small token-styled primitives: Input, Textarea, Badge, Skeleton, Panel, Kbd, Spinner. */
import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes, InputHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const field =
  "w-full rounded-md border border-line-strong bg-surface-2 px-3 text-fg placeholder:text-fg-muted " +
  "transition-colors duration-[var(--duration-fast)] hover:border-fg-muted " +
  "focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 " +
  "disabled:opacity-60 aria-invalid:border-danger";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(field, "h-10", className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, "py-2", className)} {...props} />;
}

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-micro uppercase tracking-[0.06em] [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "border-line-strong bg-surface-2 text-fg-secondary",
        accent: "border-accent/40 bg-accent-soft text-accent",
        success: "border-success/40 bg-success-soft text-success",
        warning: "border-warning/40 bg-warning-soft text-warning",
        danger: "border-danger/40 bg-danger-soft text-danger",
        info: "border-info/40 bg-info-soft text-info",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-surface-3 motion-reduce:animate-none", className)}
      {...props}
    />
  );
}

export function Panel({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("rounded-lg border border-line bg-surface-1", className)} {...props} />;
}

export function PanelHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex min-h-12 items-center justify-between gap-3 border-b border-line px-4 py-2", className)}
      {...props}
    />
  );
}

export function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-line-strong bg-surface-2 px-1 font-mono text-micro text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role={label ? "status" : undefined} className={cn("inline-flex items-center", className)}>
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none"
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}
