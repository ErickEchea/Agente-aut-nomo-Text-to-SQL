import { defineConfig, devices } from "@playwright/test";

/** E2E runs against the running stack (`make up`). Override with NEXUS_WEB_URL. */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  // In CI the github reporter turns failures into annotations readable without signing in.
  reporter: process.env["CI"] ? [["list"], ["github"]] : [["list"]],
  use: {
    baseURL: process.env["NEXUS_WEB_URL"] ?? "http://127.0.0.1:8080",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 740 } } },
  ],
});
