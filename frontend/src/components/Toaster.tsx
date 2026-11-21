import { Toaster as Sonner } from "sonner";

import { usePreferences } from "../app/preferences";

export function Toaster() {
  const { resolvedTheme } = usePreferences();
  return (
    <Sonner
      theme={resolvedTheme}
      position="bottom-right"
      closeButton
      toastOptions={{
        unstyled: false,
        classNames: {
          toast: "rounded-lg! border! border-line-strong! bg-surface-2! text-fg! shadow-overlay! font-sans!",
          description: "text-fg-secondary!",
          success: "[&_[data-icon]]:text-success!",
          error: "[&_[data-icon]]:text-danger!",
          closeButton: "border-line-strong! bg-surface-3! text-fg-secondary!",
        },
      }}
    />
  );
}
