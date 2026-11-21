/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env["NEXUS_API_URL"] ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  build: {
    sourcemap: true,
    // Never inline assets as data: URIs; the CSP only allows fonts and scripts from 'self'.
    assetsInlineLimit: 0,
    // Authenticated internal tool: the workspace entry is ~270 kB gzip; ECharts and the secondary
    // screens are separate chunks loaded on demand.
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
