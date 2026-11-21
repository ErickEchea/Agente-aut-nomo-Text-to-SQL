/** Radix-based overlays restyled with tokens: Dialog, Tooltip, DropdownMenu, Tabs, Switch. */
import { Dialog as D, DropdownMenu as M, Switch as S, Tabs as T, Tooltip as TT } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import { cn } from "../../lib/cn";

/* ------------------------------------------------------------------ Dialog */

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  ...props
}: ComponentProps<typeof D.Content> & { title: ReactNode; description?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-scrim backdrop-blur-[2px] data-[state=open]:animate-[fade-in_var(--duration-base)_ease-out]" />
      <D.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
          "rounded-xl border border-line bg-surface-1 p-5 shadow-overlay",
          "data-[state=open]:animate-[dialog-in_var(--duration-base)_var(--ease-out)]",
          className,
        )}
        {...(description ? {} : { "aria-describedby": undefined })}
        {...props}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <D.Title className="font-display text-h2 text-fg">{title}</D.Title>
            {description ? (
              <D.Description className="mt-1 text-small text-fg-secondary">{description}</D.Description>
            ) : null}
          </div>
          <D.Close
            className="-m-1 rounded-md p-1 text-fg-muted hover:bg-surface-3 hover:text-fg"
            aria-label={t("common.close")}
          >
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  );
}

/* ----------------------------------------------------------------- Tooltip */

export const TooltipProvider = TT.Provider;

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TT.Root>
      <TT.Trigger asChild>{children}</TT.Trigger>
      <TT.Portal>
        <TT.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-line-strong bg-surface-2 px-2 py-1 text-small text-fg shadow-overlay"
        >
          {content}
        </TT.Content>
      </TT.Portal>
    </TT.Root>
  );
}

/* ------------------------------------------------------------ DropdownMenu */

export const Menu = M.Root;
export const MenuTrigger = M.Trigger;

export function MenuContent({ className, ...props }: ComponentProps<typeof M.Content>) {
  return (
    <M.Portal>
      <M.Content
        sideOffset={6}
        align="end"
        className={cn(
          "z-50 min-w-44 rounded-lg border border-line bg-surface-1 p-1 shadow-overlay",
          className,
        )}
        {...props}
      />
    </M.Portal>
  );
}

export function MenuItem({ className, ...props }: ComponentProps<typeof M.Item>) {
  return (
    <M.Item
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-body text-fg-secondary outline-none select-none",
        "data-[highlighted]:bg-surface-3 data-[highlighted]:text-fg data-[disabled]:opacity-50 [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export function MenuLabel({ className, ...props }: ComponentProps<typeof M.Label>) {
  return <M.Label className={cn("label-micro px-2 py-1.5", className)} {...props} />;
}

export const MenuSeparator = () => <M.Separator className="my-1 h-px bg-line" />;
export const MenuRadioGroup = M.RadioGroup;

export function MenuRadioItem({ className, children, ...props }: ComponentProps<typeof M.RadioItem>) {
  return (
    <M.RadioItem
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-body text-fg-secondary outline-none select-none",
        "data-[highlighted]:bg-surface-3 data-[highlighted]:text-fg data-[state=checked]:text-fg",
        className,
      )}
      {...props}
    >
      <span className="flex size-4 items-center justify-center">
        <M.ItemIndicator>
          <span className="block size-1.5 rounded-full bg-accent" />
        </M.ItemIndicator>
      </span>
      {children}
    </M.RadioItem>
  );
}

/* -------------------------------------------------------------------- Tabs */

export const Tabs = T.Root;
export const TabsContent = T.Content;

export function TabsList({ className, ...props }: ComponentProps<typeof T.List>) {
  return (
    <T.List
      className={cn(
        "flex items-center gap-1 overflow-x-auto border-b border-line px-2 [scrollbar-width:none]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        "relative -mb-px inline-flex h-11 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 text-body text-fg-muted",
        "transition-colors duration-[var(--duration-fast)] hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg",
        "disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

/* ------------------------------------------------------------------ Switch */

export function Switch({ className, ...props }: ComponentProps<typeof S.Root>) {
  return (
    <S.Root
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-line-strong bg-surface-3",
        "transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent",
        className,
      )}
      {...props}
    >
      <S.Thumb className="block size-3.5 translate-x-0.5 rounded-full bg-fg-secondary transition-transform data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent-ink" />
    </S.Root>
  );
}
