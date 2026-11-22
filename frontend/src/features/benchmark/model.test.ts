import { describe, expect, it } from "vitest";

import type { BenchmarkRunOut } from "../../api/types";
import { accuracyScale, isRouted, latencyScale, modelsOf, project, seriesColors } from "./model";

function run(name: string, model: string, nodes: Record<string, string> = {}): BenchmarkRunOut {
  return { config: { name, model, nodes } } as unknown as BenchmarkRunOut;
}

describe("seriesColors", () => {
  it("follows the configuration name, not its rank", () => {
    const a = seriesColors(["qwen3-8b", "gemma4-e4b", "qwen2.5-coder-7b"]);
    const b = seriesColors(["qwen2.5-coder-7b", "qwen3-8b", "gemma4-e4b", "gemma4-e4b"]);
    expect(a).toEqual(b);
    expect(a.get("gemma4-e4b")).toBe("var(--data-1)");
    expect(a.get("qwen3-8b")).toBe("var(--data-3)");
  });
});

describe("models", () => {
  it("lists the default model first and each routed model once", () => {
    const routed = run("routed", "coder:7b", { plan: "qwen3:8b", explain: "qwen3:8b" });
    expect(modelsOf(routed)).toEqual(["coder:7b", "qwen3:8b"]);
    expect(isRouted(routed)).toBe(true);
    expect(isRouted(run("single", "coder:7b"))).toBe(false);
  });
});

describe("scales", () => {
  it("latency starts at zero and leaves headroom with round ticks", () => {
    const scale = latencyScale([12.4, 48.1, 30]);
    expect(scale.min).toBe(0);
    expect(scale.max).toBeGreaterThan(48.1);
    expect(scale.ticks[0]).toBe(0);
    expect(scale.ticks.at(-1)).toBe(scale.max);
  });

  it("accuracy reaches 100 and includes the selection band", () => {
    const scale = accuracyScale([81, 76.8, 70.4], 2);
    expect(scale.max).toBe(100);
    expect(scale.min).toBeLessThanOrEqual(70);
    expect(scale.ticks.every((t) => t % 5 === 0)).toBe(true);
    expect(accuracyScale([30, 95], 2).ticks.every((t) => t % 10 === 0)).toBe(true);
  });

  it("projects values linearly", () => {
    const scale = { min: 0, max: 10, ticks: [] };
    expect(project(5, scale, 0, 100)).toBe(50);
    expect(project(10, scale, 300, 20)).toBe(20);
  });
});
