# frontend

React 19 + TypeScript (strict) + Vite 8 · Tailwind v4 on design tokens · Radix primitives styled the
shadcn/ui way · Motion · TanStack Query / Table v9 / Virtual · ECharts 6 · Shiki · cmdk · i18next (es/en).
The design system is described in [`docs/DESIGN.md`](../docs/DESIGN.md), and the architecture in
[ADR-0016](../docs/adr/0016-frontend-stack-and-design-system.md) and
[ADR-0020](../docs/adr/0020-frontend-architecture-and-ui-hardening.md).

The production image is nginx. It serves the build under a strict CSP and reverse-proxies `/api` to the
backend, with buffering off so SSE is safe.

```bash
npm ci && npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run lint && npm run typecheck && npm run test && npm run build
npm run api:types            # regenerate src/api/schema.d.ts from the committed OpenAPI snapshot
```

| Folder | What lives there |
|---|---|
| `src/app` | providers (auth session, preferences), router, app shell, command palette |
| `src/api` | typed client, endpoints, OpenAPI snapshot + generated types, zod schemas for SSE events |
| `src/features/workspace` | query bar, conversation turns, workspace session (one SSE stream per run) |
| `src/features/timeline` | live agent timeline: pure event reducer + node renderers (SQL, repair diffs) |
| `src/features/results` | answer view: KPI cards, tabs, virtualized table, ECharts chart, feedback, pin |
| `src/features/*` | dashboards, history, connections, benchmark, audit (admin), settings, login |
| `src/styles` | `tokens.css` (the only place colors live) and Tailwind mapping; contrast tests |

**End-to-end tests** (`make e2e`, stack up) sign in with the `NEXUS_E2E_*` account from `.env`. They visit
every screen in dark and light at 1280 px and 375 px, run axe (WCAG 2.2 AA), and write screenshots to
`docs/screenshots/phase4/`. `make e2e-agent` adds the `@llm` browser run of the reference question.
