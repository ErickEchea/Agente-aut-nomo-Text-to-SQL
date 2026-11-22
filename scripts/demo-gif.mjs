#!/usr/bin/env node
// Render the README demo GIF from the video `frontend/e2e/demo.spec.ts` records (`make demo-gif`).
// Everything a person does plays at real speed; only the two waits for the model are sped up (to about
// WAIT_SECONDS each), so the live timeline stays visible. Needs ffmpeg on PATH.
//
//   node scripts/demo-gif.mjs <demo.json> <out.gif>
import { spawnSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";

const WAIT_SECONDS = 5;
// Size knobs (a README GIF should stay well under 10 MB).
const FPS = Number(process.env.DEMO_FPS ?? "8");
const WIDTH = Number(process.env.DEMO_WIDTH ?? "880");
const COLORS = Number(process.env.DEMO_COLORS ?? "64");

const [, , manifestPath, outPath] = process.argv;
if (!manifestPath || !outPath) {
  console.error("usage: node scripts/demo-gif.mjs <demo.json> <out.gif>");
  process.exit(2);
}
const { video, marks } = JSON.parse(readFileSync(manifestPath, "utf8"));
const at = Object.fromEntries(marks.map((m) => [m.label, m.at]));

// [from, to, sped up?] — the waits for the model are the only accelerated parts.
const plan = [
  ["start", "asked", false],
  ["asked", "answered", true],
  ["answered", "follow_up", false],
  ["follow_up", "follow_up_asked", false],
  ["follow_up_asked", "follow_up_answered", true],
  ["follow_up_answered", "end", false],
];

const segments = plan.map(([from, to, wait]) => {
  if (at[from] === undefined || at[to] === undefined) throw new Error(`missing mark ${from} or ${to}`);
  const length = at[to] - at[from];
  return { from: at[from], to: at[to], speed: wait ? Math.max(1, length / WAIT_SECONDS) : 1 };
});

const trims = segments
  .map((s, i) => `[0:v]trim=start=${s.from.toFixed(3)}:end=${s.to.toFixed(3)},setpts=(PTS-STARTPTS)/${s.speed.toFixed(3)}[v${i}]`)
  .join(";");
const inputs = segments.map((_, i) => `[v${i}]`).join("");
const filter =
  `${trims};${inputs}concat=n=${segments.length}:v=1:a=0,fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,split[a][b];` +
  `[a]palettegen=max_colors=${COLORS}:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`;

const result = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-i", video, "-filter_complex", filter, "-loop", "0", outPath], {
  stdio: "inherit",
});
if (result.error) {
  console.error(`ffmpeg could not run: ${result.error.message}`);
  process.exit(1);
}
if (result.status !== 0) process.exit(result.status ?? 1);

const total = segments.reduce((sum, s) => sum + (s.to - s.from) / s.speed, 0);
const waits = segments.filter((s) => s.speed > 1).map((s) => `${(s.to - s.from).toFixed(1)} s → ${WAIT_SECONDS} s`);
const mb = statSync(outPath).size / 1024 / 1024;
console.log(`${outPath}: ${total.toFixed(1)} s, ${mb.toFixed(1)} MB (model waits sped up: ${waits.join(", ")})`);
