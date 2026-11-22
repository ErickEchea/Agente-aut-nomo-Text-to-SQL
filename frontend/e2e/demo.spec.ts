/**
 * Records the README demo with the real local model (`make demo-gif`; tagged @demo, so `make e2e` skips it).
 * It asks the reference question and its follow-up through the browser, exactly as a person would, and
 * writes the video plus the time of each milestone. `scripts/demo-gif.mjs` then speeds up only the waits
 * for the model, so nothing in the GIF is staged.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { HAS_CREDENTIALS, NO_CREDENTIALS_REASON, signIn, useTheme } from "./support";

const QUESTION =
  "¿Cuáles fueron los cinco productos más vendidos durante el último trimestre y qué sucursal generó mayores ingresos?";
const FOLLOW_UP = "¿Y en el trimestre anterior?";
const OUT = resolve("test-results/demo");
const SIZE = { width: 1280, height: 800 };

test("@demo reference question and follow-up", async ({ browser }, testInfo) => {
  test.skip(!HAS_CREDENTIALS, NO_CREDENTIALS_REASON);
  test.skip(testInfo.project.name !== "desktop", "recorded once, at desktop size");
  test.setTimeout(900_000);
  mkdirSync(OUT, { recursive: true });

  const context = await browser.newContext({
    baseURL: testInfo.project.use.baseURL ?? "http://127.0.0.1:8080",
    viewport: SIZE,
    recordVideo: { dir: OUT, size: SIZE },
  });
  const started = Date.now();
  const marks: { label: string; at: number }[] = [];
  const mark = (label: string): void => {
    marks.push({ label, at: (Date.now() - started) / 1000 });
  };
  const page = await context.newPage();
  await useTheme(page, "dark");
  await signIn(page);
  const input = page.getByLabel("Tu pregunta");
  await expect(input).toBeVisible();
  await page.waitForTimeout(800);

  mark("start");
  await input.pressSequentially(QUESTION, { delay: 28 });
  await page.waitForTimeout(400);
  await page.keyboard.press("Enter");
  mark("asked");
  const answered = page.getByText("Respondida", { exact: true });
  await expect(answered).toHaveCount(1, { timeout: 360_000 });
  mark("answered");

  const answer = page.locator("article").first();
  await page.waitForTimeout(3500);
  await answer.getByRole("tab", { name: "Gráfico" }).click();
  await page.waitForTimeout(2500);
  await answer.getByRole("tab", { name: "Explicación" }).click();
  await page.waitForTimeout(3500);

  mark("follow_up");
  await input.pressSequentially(FOLLOW_UP, { delay: 45 });
  await page.waitForTimeout(400);
  await page.keyboard.press("Enter");
  mark("follow_up_asked");
  await expect(answered).toHaveCount(2, { timeout: 360_000 });
  mark("follow_up_answered");
  await page.locator("article").last().scrollIntoViewIfNeeded();
  await page.waitForTimeout(4500);
  mark("end");

  const video = page.video();
  await context.close(); // finalizes the video file
  const path = video ? await video.path() : null;
  expect(path).not.toBeNull();
  writeFileSync(resolve(OUT, "demo.json"), JSON.stringify({ video: path, marks }, null, 2));
});
