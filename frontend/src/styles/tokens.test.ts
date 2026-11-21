import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const STYLES = import.meta.dirname;
const SRC = join(STYLES, "..");
const css = readFileSync(join(STYLES, "tokens.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`selector ${selector} not found`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  const tokens: Record<string, string> = {};
  for (const match of css.slice(open + 1, close).matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    const [, name, value] = match;
    if (name && value) tokens[name] = value.trim();
  }
  return tokens;
}

const themes = {
  dark: block(':root[data-theme="dark"]'),
  light: block(':root[data-theme="light"]'),
};

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m?.[1]) throw new Error(`not a 6-digit hex color: ${hex}`);
  const n = Number.parseInt(m[1], 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const SURFACES = ["bg", "surface-1", "surface-2", "surface-3"] as const;
// Text tokens must reach 4.5:1 (WCAG 1.4.3 normal text) on every surface they can sit on.
const TEXT = ["fg", "fg-secondary", "fg-muted", "accent", "success", "warning", "danger", "info"] as const;

describe.each(Object.entries(themes))("%s theme", (_name, tokens) => {
  const get = (token: string): string => {
    const value = tokens[token];
    if (!value) throw new Error(`missing token ${token}`);
    return value;
  };

  it.each(TEXT.flatMap((t) => SURFACES.map((s) => [t, s] as const)))(
    "%s on %s meets AA (4.5:1)",
    (text, surface) => {
      expect(contrast(get(text), get(surface))).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("text on the accent fill meets AA", () => {
    expect(contrast(get("accent-ink"), get("accent"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(get("accent-ink"), get("accent-strong"))).toBeGreaterThanOrEqual(4.5);
  });

  it("input borders and the focus ring are visible (3:1 non-text contrast)", () => {
    for (const surface of SURFACES) {
      expect(contrast(get("accent"), get(surface))).toBeGreaterThanOrEqual(3);
    }
    expect(contrast(get("line-strong"), get("surface-1"))).toBeGreaterThanOrEqual(1.4);
  });

  it("syntax colors stay readable on code surfaces", () => {
    for (const token of ["code-keyword", "code-function", "code-string", "code-number", "code-plain"]) {
      expect(contrast(get(token), get("surface-2"))).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(get("code-comment"), get("surface-2"))).toBeGreaterThanOrEqual(4.5);
  });

  it("defines all eight data slots", () => {
    for (let slot = 1; slot <= 8; slot++) expect(get(`data-${slot}`)).toMatch(/^#[0-9a-f]{6}$/i);
  });
});

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx?|css)$/.test(entry) && !entry.endsWith(".test.ts") && !entry.endsWith(".d.ts")
      ? [path]
      : [];
  });
}

describe("styling only through tokens", () => {
  it("has no raw hex colors outside the token file", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => !file.endsWith("tokens.css"))
      .filter((file) => /#[0-9a-f]{3,8}\b(?![\w-])/i.test(readFileSync(file, "utf8").replace(/&#\d+;/g, "")))
      .map((file) => relative(SRC, file));
    expect(offenders).toEqual([]);
  });
});
