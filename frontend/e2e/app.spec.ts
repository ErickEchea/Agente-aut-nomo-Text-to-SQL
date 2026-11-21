import { expect, test, type Page } from "@playwright/test";

import {
  E2E_EMAIL,
  HAS_CREDENTIALS,
  NO_CREDENTIALS_REASON,
  expectAccessible,
  expectNoHorizontalScroll,
  openSession,
  screenshot,
  setTheme,
  useTheme,
  watchErrors,
} from "./support";

test("API is served through the same origin with a request id", async ({ request }) => {
  const response = await request.get("/api/health/ready");
  expect(response.status()).toBe(200);
  expect(response.headers()["x-request-id"]).toMatch(/^[A-Za-z0-9._-]{1,64}$/);
  expect(((await response.json()) as { status: string }).status).toBe("ready");
});

test("unauthenticated visitors are sent to the login page", async ({ page }) => {
  await page.goto("/dashboards");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Inicia sesión" })).toBeVisible();
});

test("wrong credentials show an actionable error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Correo electrónico").fill("nadie@nexus.local");
  await page.getByLabel("Contraseña").fill("incorrecta-123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("alert")).toHaveText("Correo o contraseña incorrectos.");
});

for (const scheme of ["dark", "light"] as const) {
  test(`login screen (${scheme})`, async ({ page }, testInfo) => {
    const errors = watchErrors(page);
    await useTheme(page, scheme);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Inicia sesión" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
    await page.waitForTimeout(1200); // let the hero animation settle before the screenshot
    await expectNoHorizontalScroll(page);
    await expectAccessible(page);
    await screenshot(page, testInfo, "login", scheme);
    expect(errors).toEqual([]);
  });
}

const SCREENS = [
  { path: "/", name: "workspace", heading: /¿Qué quieres saber hoy\?/ },
  { path: "/dashboards", name: "dashboards", heading: "Dashboards" },
  { path: "/history", name: "history", heading: "Historial y memoria" },
  { path: "/connections", name: "connections", heading: "Conexiones" },
  { path: "/benchmark", name: "benchmark", heading: "Benchmark de modelos" },
  { path: "/audit", name: "audit", heading: "Auditoría" },
  { path: "/settings", name: "settings", heading: "Configuración" },
] as const;

// One sign-in per project: logins are rate limited (5/min per client) and that limit stays on.
test.describe("signed in", () => {
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

  for (const scheme of ["dark", "light"] as const) {
    test(`every screen renders, is accessible and fits the viewport (${scheme})`, async ({}, testInfo) => {
      test.setTimeout(120_000);
      errors.length = 0;
      await setTheme(page, scheme);
      for (const screen of SCREENS) {
        await page.goto(screen.path);
        await expect(page.getByRole("heading", { level: 1, name: screen.heading })).toBeVisible();
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(500);
        await expectNoHorizontalScroll(page);
        await expectAccessible(page);
        await screenshot(page, testInfo, screen.name, scheme);
      }
      expect(errors).toEqual([]);
    });
  }

  test("command palette navigates with the keyboard", async () => {
    await page.goto("/");
    await expect(page.getByLabel("Tu pregunta")).toBeVisible(); // the shell (and its shortcut) is mounted
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Paleta de comandos" });
    await expect(palette).toBeVisible();
    await page.keyboard.type("Conexiones");
    // A screen name navigates; asking the agent is the fallback, listed last.
    await expect(palette.getByRole("option", { name: "Conexiones", exact: true })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/connections$/);
    await expect(palette).toBeHidden();
  });

  test("language and theme preferences apply instantly", async () => {
    await setTheme(page, "dark");
    await page.goto("/settings");
    await page.getByRole("radio", { name: "Claro" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("radio", { name: "English" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    // Back to the defaults so the account keeps Spanish for the other tests.
    await page.getByRole("radio", { name: "Español" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Configuración" })).toBeVisible();
    await page.getByRole("radio", { name: "Oscuro" }).click();
  });

  test("the account menu shows the role and signs out", async () => {
    await page.goto("/");
    await page.getByRole("button", { name: "Cuenta" }).click();
    await expect(page.getByRole("menu").getByText(E2E_EMAIL)).toBeVisible();
    await expect(page.getByRole("menu").getByText("Administrador")).toBeVisible();
    await page.getByRole("menuitem", { name: "Cerrar sesión" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});
