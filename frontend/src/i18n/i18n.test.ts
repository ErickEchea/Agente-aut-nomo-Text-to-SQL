import { describe, expect, it } from "vitest";

import { resources } from "./resources";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

function placeholders(value: unknown): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (v: unknown, path: string) => {
    if (typeof v === "string") out.set(path, [...v.matchAll(/{{(\w+)}}/g)].map((m) => m[1]).sort().join(","));
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, `${path}.${k}`);
  };
  walk(value, "");
  return out;
}

describe("translations", () => {
  it("English mirrors every Spanish key", () => {
    expect(keys(resources.en.translation).sort()).toEqual(keys(resources.es.translation).sort());
  });

  it("uses the same interpolation variables in both languages", () => {
    const es = placeholders(resources.es.translation);
    const en = placeholders(resources.en.translation);
    for (const [path, vars] of es) expect([path, en.get(path)]).toEqual([path, vars]);
  });

  it("names every agent node in both languages", () => {
    expect(Object.keys(resources.es.translation.timeline.nodes)).toHaveLength(13);
  });
});
