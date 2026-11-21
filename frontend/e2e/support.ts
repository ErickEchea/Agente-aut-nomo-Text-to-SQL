import AxeBuilder from "@axe-core/playwright";
import { expect, type Browser, type Page, type TestInfo } from "@playwright/test";

export const SCREENSHOTS = "../docs/screenshots/phase4";
export const E2E_EMAIL = process.env["NEXUS_E2E_EMAIL"] ?? "";
export const E2E_PASSWORD = process.env["NEXUS_E2E_PASSWORD"] ?? "";
export const HAS_CREDENTIALS = E2E_EMAIL !== "" && E2E_PASSWORD !== "";
export const NO_CREDENTIALS_REASON = "set NEXUS_E2E_EMAIL / NEXUS_E2E_PASSWORD (make e2e does it from .env)";

export type Scheme = "dark" | "light";

/** Theme is chosen in the app (dark default); the stored preference is what the app reads first. */
export async function useTheme(page: Page, scheme: Scheme): Promise<void> {
  await page.addInitScript((value) => {
    window.localStorage.setItem("nexus.theme", value);
    window.localStorage.setItem("nexus.locale", "es");
  }, scheme);
}

export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Correo electrónico").fill(E2E_EMAIL);
  await page.getByLabel("Contraseña").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/$/);
}

/**
 * A signed-in page shared by a serial describe block (logins are rate limited, so each project
 * signs in once). The access token lives in memory; reloads restore it from the refresh cookie.
 */
export async function openSession(browser: Browser, testInfo: TestInfo): Promise<Page> {
  const { baseURL, viewport, colorScheme } = testInfo.project.use;
  const context = await browser.newContext({
    baseURL: baseURL ?? "http://127.0.0.1:8080",
    viewport: viewport ?? null,
    ...(colorScheme ? { colorScheme } : {}),
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    if (!window.localStorage.getItem("nexus.locale")) window.localStorage.setItem("nexus.locale", "es");
  });
  await signIn(page);
  return page;
}

/** Switch the stored theme and reload (the session survives through the refresh cookie). */
export async function setTheme(page: Page, scheme: Scheme): Promise<void> {
  await page.evaluate((value) => {
    window.localStorage.setItem("nexus.theme", value);
  }, scheme);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
  await expect(page.locator("#main")).toBeVisible(); // signed in again through the refresh cookie
}

/** Collect page errors and console errors (the anonymous session probe's 401 is expected). */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401")) errors.push(message.text());
  });
  return errors;
}

export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** WCAG 2.2 A/AA checks with axe-core. */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  expect(summary).toEqual([]);
}

export async function screenshot(page: Page, testInfo: TestInfo, name: string, scheme: Scheme): Promise<void> {
  await page.screenshot({ path: `${SCREENSHOTS}/${name}-${testInfo.project.name}-${scheme}.png` });
}
