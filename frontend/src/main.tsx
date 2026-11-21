import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "./styles/index.css";
import "./i18n";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";

import { ApiError } from "./api/client";
import { AuthProvider } from "./app/auth";
import { PreferencesProvider } from "./app/preferences";
import { router } from "./app/router";
import { Toaster } from "./components/Toaster";
import { TooltipProvider } from "./components/ui/overlays";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Client errors will not fix themselves; retry only transient failures.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <AuthProvider>
          <TooltipProvider delayDuration={300}>
            <RouterProvider router={router} />
            <Toaster />
          </TooltipProvider>
        </AuthProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  </StrictMode>,
);
