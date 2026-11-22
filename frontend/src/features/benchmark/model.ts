/** Pure helpers for the Benchmark page: stable series colors, models, chart scales. */
import type { BenchmarkRunOut } from "../../api/types";

export const DIFFICULTIES = ["easy", "medium", "hard", "ambiguous"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

const SERIES = 8;

/** Color follows the configuration, never its rank: index by sorted name, capped at the palette size. */
export function seriesColors(names: readonly string[]): Map<string, string> {
  const sorted = [...new Set(names)].sort((a, b) => a.localeCompare(b));
  return new Map(sorted.map((name, i) => [name, `var(--data-${(i % SERIES) + 1})`]));
}

/** Every model a configuration uses (default first, then per-node routes). */
export function modelsOf(run: BenchmarkRunOut): string[] {
  const nodes = Object.values(run.config.nodes ?? {}).filter((m): m is string => typeof m === "string");
  return [...new Set([run.config.model, ...nodes])];
}

export function isRouted(run: BenchmarkRunOut): boolean {
  return Object.keys(run.config.nodes ?? {}).length > 0;
}

export interface Scale {
  min: number;
  max: number;
  ticks: number[];
}

function step(span: number): number {
  const raw = span / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return nice * magnitude;
}

/** Latency axis in seconds, from 0 to a rounded maximum with room for the largest point. */
export function latencyScale(seconds: readonly number[]): Scale {
  const top = Math.max(1, ...seconds) * 1.12;
  const unit = step(top);
  const max = Math.ceil(top / unit) * unit;
  const ticks = Array.from({ length: Math.round(max / unit) + 1 }, (_, i) => +(i * unit).toFixed(6));
  return { min: 0, max, ticks };
}

/** Accuracy axis in percent: from a rounded floor below the worst configuration (and the band) to 100. */
export function accuracyScale(percents: readonly number[], margin: number): Scale {
  const lowest = Math.min(100, ...percents, Math.max(...percents, 0) - margin);
  const unit = 100 - lowest > 40 ? 10 : 5;
  const min = Math.max(0, Math.floor((lowest - unit / 2) / unit) * unit);
  const ticks = Array.from({ length: Math.round((100 - min) / unit) + 1 }, (_, i) => min + i * unit);
  return { min, max: 100, ticks };
}

export function project(value: number, scale: Scale, from: number, to: number): number {
  const span = scale.max - scale.min || 1;
  return from + ((value - scale.min) / span) * (to - from);
}
