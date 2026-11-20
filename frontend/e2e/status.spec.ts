import { expect, test } from "@playwright/test";

const SCREENSHOT_DIR = "../docs/screenshots/phase1";

for (const scheme of ["dark", "light"] as const) {
  test(`status page shows a healthy stack (${scheme})`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Estado del sistema" })).toBeVisible();
    await expect(page.getByText("Operativo")).toBeVisible({ timeout: 15_000 });
    for (const label of [
      "Base de datos de la aplicación",
      "Base de datos retail (solo lectura)",
      "Modelos locales (Ollama)",
    ]) {
      await expect(page.getByText(label)).toBeVisible();
    }
    await expect(page.getByText("read_only: true")).toBeVisible();

    // No horizontal scrolling at any viewport.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/status-${testInfo.project.name}-${scheme}.png`,
      fullPage: true,
    });
  });
}

test("language switch to English", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Idioma").selectOption("en");
  await expect(page.getByRole("heading", { name: "System status" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("API is served through the same origin with a request id", async ({ request }) => {
  const response = await request.get("/api/health/ready");
  expect(response.status()).toBe(200);
  expect(response.headers()["x-request-id"]).toMatch(/^[A-Za-z0-9._-]{1,64}$/);
  const body = (await response.json()) as { status: string };
  expect(body.status).toBe("ready");
});
