/**
 * The reference question through the browser with the real local model (slow, tagged @llm; run with
 * `make e2e-agent`, one worker so the desktop run happens before the other projects reuse it).
 * Covers the live timeline, every result tab, pinning to a dashboard and the answered screens.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  HAS_CREDENTIALS,
  NO_CREDENTIALS_REASON,
  expectAccessible,
  expectNoHorizontalScroll,
  openSession,
  screenshot,
  setTheme,
  watchErrors,
} from "./support";

const QUESTION =
  "¿Cuáles fueron los cinco productos más vendidos durante el último trimestre y qué sucursal generó mayores ingresos?";
const FINAL = /^(Respondida|Falló|Rechazada|Necesita aclaración)$/;

test.describe("@llm reference question in the browser", () => {
  test.skip(!HAS_CREDENTIALS, NO_CREDENTIALS_REASON);
  test.describe.configure({ mode: "serial" });

  let page: Page;
  let errors: string[];

  test.beforeAll(async ({ browser }, testInfo) => {
    page = await openSession(browser, testInfo);
    errors = watchErrors(page);
  });

  test.afterAll(async () => {
    await page.context().close();
  });

  /** Reopen the newest answered run of the reference question from History. */
  async function openLatestAnswer(): Promise<void> {
    await page.goto("/history");
    const link = page
      .getByRole("link")
      .filter({ hasText: "cinco productos" })
      .filter({ hasText: "Respondida" })
      .first();
    await link.click();
    await expect(page.getByText(FINAL).first()).toHaveText("Respondida", { timeout: 30_000 });
  }

  test("asks, streams the timeline live and answers correctly", async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the live run happens once, on desktop");
    test.setTimeout(420_000);
    await setTheme(page, "dark");
    await page.getByLabel("Tu pregunta").fill(QUESTION);
    await page.keyboard.press("Enter");

    const timeline = page.getByRole("region", { name: "Razonamiento del agente" });
    await expect(timeline.getByText("En vivo")).toBeVisible({ timeout: 30_000 });
    await expect(timeline.getByText("Comprender")).toBeVisible();
    await page.waitForTimeout(4000);
    await screenshot(page, testInfo, "workspace-live", "dark");

    await expect(page.getByText(FINAL).first()).toHaveText("Respondida", { timeout: 360_000 });
    const answer = page.locator("article").first();
    await expect(answer).toContainText("Agua mineral 1.5 L");
    await expect(answer).toContainText("Samborondón");
    await expect(answer.getByText("Cifras verificadas contra los datos")).toBeVisible();
    await expect(answer.getByText(/«último trimestre» = 1 jul 2026 – 30 sept? 2026/)).toBeVisible();

    await answer.getByRole("tab", { name: "Tabla" }).click();
    await expect(answer.getByRole("tabpanel")).toContainText("Agua mineral");
    await answer.getByRole("tab", { name: "Gráfico" }).click();
    await expect(answer.locator("canvas").first()).toBeVisible();
    await answer.getByRole("tab", { name: "SQL" }).click();
    await expect(answer.locator("pre code").first()).toContainText(/SELECT/i);
    await answer.getByRole("tab", { name: "Optimización" }).click();
    await expect(answer.getByText("Fase 5", { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("pins the answer to a new dashboard and shows it there", async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the dashboard flow runs once");
    await openLatestAnswer();
    await page.getByRole("button", { name: "Fijar en dashboard" }).click();
    const dialog = page.getByRole("dialog", { name: "Fijar en un dashboard" });
    await dialog.getByLabel("Dashboard", { exact: true }).selectOption({ label: "Nuevo dashboard" });
    const name = `E2E ${Date.now()}`;
    await dialog.getByLabel("Nombre del nuevo dashboard").fill(name);
    await dialog.getByRole("button", { name: "Fijar" }).click();
    await expect(page.getByText(`Fijado en «${name}».`)).toBeVisible();

    await page.goto("/dashboards");
    await page.getByRole("link", { name: new RegExp(name) }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await page.waitForTimeout(1200);
    await expectNoHorizontalScroll(page);
    await expectAccessible(page);
    await screenshot(page, testInfo, "dashboard", "dark");

    await page.getByRole("button", { name: "Eliminar" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Eliminar" }).click();
    await expect(page).toHaveURL(/\/dashboards$/);
  });

  for (const scheme of ["dark", "light"] as const) {
    test(`answered workspace (${scheme})`, async ({}, testInfo) => {
      await setTheme(page, scheme);
      await openLatestAnswer();
      await page.waitForTimeout(1200);
      await expectNoHorizontalScroll(page);
      await expectAccessible(page);
      await screenshot(page, testInfo, "workspace-answer", scheme);
      await page.getByRole("tab", { name: "SQL" }).first().click();
      await page.getByRole("tabpanel").first().scrollIntoViewIfNeeded();
      await expectNoHorizontalScroll(page);
      await screenshot(page, testInfo, "workspace-sql", scheme);
    });
  }
});
