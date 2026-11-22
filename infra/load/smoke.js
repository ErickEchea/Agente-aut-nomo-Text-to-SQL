// Load sanity check (Phase 7, ADR-0023). Two questions, measured at the same time:
//   1. Does the API stay responsive for people browsing while the agent works?
//   2. How do concurrent questions queue on one local GPU (OLLAMA_NUM_PARALLEL=1)?
// Not a capacity benchmark: one backend replica, one GPU. Run with `make load` (stack up); the report is
// written to docs/load-test.md. Requests go through nginx, exactly like the browser's.
import exec from "k6/execution";
import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE = __ENV.NEXUS_WEB_URL || "http://frontend:8080";
const PASSWORD = __ENV.NEXUS_LOAD_PASSWORD || "";
const USERS = Number(__ENV.LOAD_USERS || "4");
const QUESTIONS_PER_USER = Number(__ENV.LOAD_QUESTIONS || "2");
const BROWSE_RATE = Number(__ENV.LOAD_BROWSE_RATE || "20");
const BROWSE_DURATION = __ENV.LOAD_BROWSE_DURATION || "4m";
const REPORT = __ENV.LOAD_REPORT || "/out/load-test.md";
const RUN_TIMEOUT_MS = 10 * 60 * 1000;

// Easy golden-set questions (bench/golden/easy.yaml): this measures concurrency, not accuracy.
const QUESTIONS = [
  "¿Cuántas sucursales tiene la cadena?",
  "¿Cuántos productos hay en el catálogo?",
  "¿Cuántos clientes registrados hay en cada segmento?",
  "¿Qué sucursales tienen formato express?",
];

// The read endpoints the screens call while someone browses.
const READS = [
  ["me", "/api/auth/me"],
  ["history", "/api/runs?limit=20"],
  ["dashboards", "/api/dashboards"],
  ["connections", "/api/connections"],
  ["benchmark", "/api/benchmark"],
  ["frequent", "/api/memory/frequent"],
];

const TERMINAL = ["answered", "clarification", "refused", "failed", "cancelled"];
const runSeconds = new Trend("agent_run_seconds");
const runCompleted = new Rate("agent_run_completed");
const runStartRejected = new Counter("agent_run_start_rejected");
const runStatus = Object.fromEntries(
  [...TERMINAL, "timeout"].map((s) => [s, new Counter(`agent_runs_${s}`)]),
);

// One scenario per load user: the API allows one run at a time per user, so each user asks in turn.
const askScenarios = Object.fromEntries(
  Array.from({ length: USERS }, (_, i) => [
    `ask_${i + 1}`,
    {
      executor: "per-vu-iterations",
      exec: "ask",
      vus: 1,
      iterations: QUESTIONS_PER_USER,
      maxDuration: "20m",
      env: { LOAD_USER: String(i + 1) },
    },
  ]),
);

export const options = {
  scenarios: {
    browse: {
      executor: "constant-arrival-rate",
      exec: "browse",
      rate: BROWSE_RATE,
      timeUnit: "1s",
      duration: BROWSE_DURATION,
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
    ...askScenarios,
  },
  thresholds: {
    "http_req_failed{scenario:browse}": ["rate<0.01"],
    "http_req_duration{scenario:browse}": ["p(95)<500"],
    "http_reqs{scenario:browse}": ["count>0"],
    ...Object.fromEntries(READS.map(([name]) => [`http_req_duration{endpoint:${name}}`, ["p(95)<1000"]])),
    // Count thresholds only make the per-endpoint request counts appear in the report.
    ...Object.fromEntries(READS.map(([name]) => [`http_reqs{endpoint:${name}}`, ["count>0"]])),
    agent_run_completed: ["rate>0.99"],
    agent_run_start_rejected: ["count<1"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

function login(email) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const res = http.post(`${BASE}/api/auth/login`, JSON.stringify({ email, password: PASSWORD }), {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "login" },
    });
    if (res.status === 200) return res.json("access_token");
    if (res.status !== 429) fail(`login ${email}: HTTP ${res.status} (\`make load\` creates the load users)`);
    sleep(Number(res.headers["Retry-After"] || "15")); // logins are rate limited (5/min per client)
  }
  return fail(`login ${email}: still rate limited`);
}

export function setup() {
  if (!PASSWORD) fail("NEXUS_LOAD_PASSWORD is empty: run `make env` to add it to .env");
  return { tokens: Array.from({ length: USERS }, (_, i) => login(`load-${i + 1}@nexus.local`)) };
}

export function browse(data) {
  const n = exec.scenario.iterationInTest;
  const [name, path] = READS[n % READS.length];
  const res = http.get(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${data.tokens[n % data.tokens.length]}` },
    tags: { endpoint: name },
  });
  check(res, { "read answered 200": (r) => r.status === 200 });
}

export function ask(data) {
  const user = Number(__ENV.LOAD_USER);
  const headers = { Authorization: `Bearer ${data.tokens[user - 1]}`, "Content-Type": "application/json" };
  const question = QUESTIONS[(user - 1 + exec.vu.iterationInScenario) % QUESTIONS.length];
  const started = Date.now();
  const res = http.post(`${BASE}/api/runs`, JSON.stringify({ question }), {
    headers,
    tags: { endpoint: "start_run" },
  });
  if (res.status !== 202) {
    runStartRejected.add(1);
    return;
  }
  const runId = res.json("run_id");
  let status = "running";
  while (!TERMINAL.includes(status) && Date.now() - started < RUN_TIMEOUT_MS) {
    sleep(2);
    const poll = http.get(`${BASE}/api/runs/${runId}`, { headers, tags: { endpoint: "run_status" } });
    if (poll.status === 200) status = poll.json("status");
  }
  if (!TERMINAL.includes(status)) status = "timeout";
  runSeconds.add((Date.now() - started) / 1000);
  runCompleted.add(status !== "failed" && status !== "timeout" && status !== "cancelled");
  runStatus[status].add(1);
}

// ---- report --------------------------------------------------------------------------------------

const ms = (v) => (v === undefined ? "–" : `${Math.round(v)} ms`);
const s = (v) => (v === undefined ? "–" : `${v.toFixed(1)} s`);

function durationRow(label, metric, requests, failed) {
  const v = metric ? metric.values : {};
  const n = requests ? requests.values.count : "–";
  const fail = failed ? `${(failed.values.rate * 100).toFixed(2)} %` : "–";
  return `| ${label} | ${n} | ${fail} | ${ms(v.med)} | ${ms(v["p(95)"])} | ${ms(v["p(99)"])} | ${ms(v.max)} |`;
}

export function handleSummary(data) {
  const m = data.metrics;
  const reqs = m["http_reqs{scenario:browse}"];
  const browseDuration = m["http_req_duration{scenario:browse}"];
  const count = (name) => (m[name] ? m[name].values.count : 0);
  const started = USERS * QUESTIONS_PER_USER - count("agent_run_start_rejected");
  const thresholds = Object.entries(m)
    .filter(([name]) => !name.startsWith("http_reqs"))
    .flatMap(([name, metric]) =>
      Object.entries(metric.thresholds || {}).map(([rule, r]) => `| \`${name}\` | \`${rule}\` | ${r.ok ? "✅" : "❌"} |`),
    )
    .sort();
  const run = m.agent_run_seconds ? m.agent_run_seconds.values : {};
  const lines = [
    "# Load sanity check",
    "",
    "> Generated by `make load` (k6, [`infra/load/smoke.js`](../infra/load/smoke.js)). Do not edit by hand.",
    "",
    `- Date: ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
    `- Model: \`${__ENV.NEXUS_LLM_MODEL || "unknown"}\` · hardware: ${__ENV.LOAD_HARDWARE || "unknown"}`,
    `- Browsing: ${BROWSE_RATE} requests/s for ${BROWSE_DURATION} over ${READS.length} read endpoints, through nginx.`,
    `- Asking: ${USERS} users at the same time, ${QUESTIONS_PER_USER} questions each (one run per user at a time).`,
    "",
    "## Browsing while the agent works",
    "",
    "| Endpoint | Requests | Failed | p50 | p95 | p99 | max |",
    "|---|---|---|---|---|---|---|",
    durationRow("**all reads**", browseDuration, reqs, m["http_req_failed{scenario:browse}"]),
    ...READS.map(([name, path]) =>
      durationRow(`\`${path}\``, m[`http_req_duration{endpoint:${name}}`], m[`http_reqs{endpoint:${name}}`]),
    ),
    "",
    "## Concurrent questions",
    "",
    "| Runs started | Rejected at start | Completed | Failed / timed out | p50 | p95 | max |",
    "|---|---|---|---|---|---|---|",
    `| ${started} | ${count("agent_run_start_rejected")} | ${count("agent_runs_answered") + count("agent_runs_clarification") + count("agent_runs_refused")} | ${count("agent_runs_failed") + count("agent_runs_timeout")} | ${s(run.med)} | ${s(run["p(95)"])} | ${s(run.max)} |`,
    "",
    `Statuses: ${[...TERMINAL, "timeout"].map((st) => `${st} ${count(`agent_runs_${st}`)}`).join(" · ")}.`,
    "",
    "## Thresholds",
    "",
    "| Metric | Rule | Result |",
    "|---|---|---|",
    ...thresholds,
    "",
  ];
  const report = lines.join("\n");
  return { [REPORT]: report, stdout: `${report}\n` };
}
