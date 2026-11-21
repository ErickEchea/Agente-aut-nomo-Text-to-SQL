# ADR-0020 — Frontend architecture and UI hardening (Phase 4 implementation)

- Status: Accepted
- Date: 2026-11-21 (Phase 4)
- Refines: ADR-0009 (SSE), ADR-0010 (auth), ADR-0016 (frontend stack and design system), ADR-0018 (guards)

## Context
Phase 4 built the web UI on top of the Phase 2–3 API. The design system is specified in
[`docs/DESIGN.md`](../DESIGN.md). This ADR records the structural decisions and what visual QA uncovered.
QA covered Playwright screenshots of every screen (dark/light × 1280 px/375 px), axe checks, and a live run of
the reference question in the browser.

## Decisions

### Contract and state
1. **Typed contract from OpenAPI.**
   - `python -m nexus.openapi` writes a snapshot (`frontend/src/api/openapi.json`) from the routers alone, with
     no settings or databases. `openapi-typescript` turns it into `schema.d.ts`.
   - A backend unit test fails when the snapshot drifts from the routes (`make api-types` regenerates both).
   - Response models declare `json_schema_serialization_defaults_required`, so fields that always come back are
     not optional in TypeScript.
   - `GET /api/runs/{id}` now returns a typed `RunResult` instead of a free-form dict.
2. **SSE events are validated at the edge.**
   - Event payloads are not in OpenAPI, so zod schemas in `api/events.ts` parse them. Malformed or unknown
     events are dropped, not rendered.
   - A pure reducer (`features/timeline/model.ts`) folds events into timeline items. It is unit-tested without
     a DOM.
   - Finished runs replay their stored events, so History and dashboards show the same timeline as a live run.
3. **SSE over `fetch`, not `EventSource`.**
   - `EventSource` cannot send `Authorization`. The fetch-based parser handles CR/LF/CRLF split across
     chunks, multi-line data and comments.
   - It reconnects with `Last-Event-ID`.
   - On a 401 it refreshes the token once; other 4xx responses are not retried.
4. **The workspace session sits above the routes.** The conversation (turns, conversation id) and one stream
   per run live in a provider, so leaving the workspace keeps the conversation and its live streams.

### Session handling in the browser (refines ADR-0010)
5. **The access token lives in memory only**, held by a `SessionManager` outside React state.
   - Concurrent refreshes are coalesced into one request, because rotation has reuse detection.
   - A timer refreshes the token 60 s before it expires.
6. **Refresh and logout use `fetch(..., { keepalive: true })`.**
   - *Found during QA:* when a navigation landed while the boot-time refresh was in flight, the browser
     aborted the request after the server had already rotated the token. The browser kept the old cookie, so
     the next refresh looked like token theft and the server revoked the session.
   - With `keepalive` the request completes and its `Set-Cookie` is stored after the page unloads.
   - Verified with a stress repro of 15 reload-then-navigate cycles inside the refresh window. Before the fix
     the session was lost on the first aborted refresh; after it, the session survives. The reuse detection
     itself is unchanged; we did not add a grace window that would also help a thief.

### Design system mechanics (refines ADR-0016)
7. **Tokens are CSS variables, mapped into Tailwind v4 with `@theme inline`.** Raw tokens that would collide
   with Tailwind theme names (fonts, radii, easing, shadow) use an `--nx-` prefix. Two tests guard them:
   - `tokens.test.ts` checks WCAG AA contrast for every text/surface pair in both themes and the 3:1 contrast
     of focus and accent elements.
   - The same file fails on any hex color outside `tokens.css`.
8. **Chart colors come from the dataviz method.** Eight categorical slots in a fixed order, validated with the
   OKLab/CVD checker against our own chart surfaces (dark `#12161b`, light `#ffffff`).
   - The light theme gets a contrast WARN for three slots. The relief is in place: a Table tab and exact
     tooltips on every chart.
   - The ECharts option is built from the validated spec plus tokens read at runtime, so charts follow theme
     switches. Mark specs: bars ≤ 24 px with rounded data ends, 2 px lines, ringed markers, hairline grids and
     a legend only for two or more series.
   - Long category labels switch to horizontal bars. Narrow containers get shorter labels and fewer ticks.
9. **The strict CSP is kept.**
   - Shiki uses the JavaScript regex engine (no WASM) and a CSS-variables theme mapped to the code tokens.
   - Fonts are self-hosted via Fontsource. Vite's `assetsInlineLimit` is 0: small fonts had been inlined as
     `data:` URIs, which `font-src 'self'` blocks.
   - The pre-paint theme script is an external file, since inline scripts are forbidden.
10. **The bundle is split.** ECharts (~190 kB gzip) loads only when a chart is shown, and the secondary
    screens are lazy routes. The workspace entry is ~270 kB gzip.
11. **No literal UI strings.** ESLint `i18next/no-literal-string` enforces it. A unit test checks that `en`
    mirrors every `es` key and interpolation variable.

### Features
12. **Dashboards hold references, not copies.** An item points to `(run_id, step)` and renders from the stored
    result, which is immutable once a run finishes.
    - Dashboards are private until shared (ADR-0010: viewers see shared dashboards).
    - Analysts and admins create and pin. Only the owner (or an admin) edits.
    - Deleting a run cascades to its items. Accepted: runs are never deleted by the UI.
13. **`GET /api/connections` is read-only.** It describes the configured source: tables with comments,
    planner row estimates (the seed loader now runs `ANALYZE`) and the retrieval index state.
    - Host, port and database role are returned to admins only.
    - Multi-connection management is Phase 5.
14. **The Benchmark and Optimization tabs show honest empty states** with the phase that delivers them. No
    sample numbers are shown.

### Deterministic guards added after the live QA run (refines ADR-0018)
15. **A plan made of SQL is discarded.**
    - The planner (qwen2.5-coder:7b) once answered with MySQL statements (`CURDATE()`) instead of
      sub-questions. Every later attempt inherited them, and the run failed after three repairs.
    - Any step that looks like SQL now drops the plan in favour of the standalone question. The timeline
      shows the rejection.
16. **Charts never plot identifiers.**
    - The rule picked the first numeric column, `producto_id`, for the top-5 bar chart.
    - Identifier-like columns (`id`, `*_id`, codes, cédula, year) are excluded from measures. The measure
      named in the question wins ("vendidos" → `unidades_vendidas`), then aggregate-like names, then the last
      column. KPI cards apply the same exclusion.

### Testing
17. **Playwright uses a dedicated account.**
    - `make e2e` provisions `NEXUS_E2E_EMAIL` from `.env` with `nexus-admin create-user --if-missing`,
      which is idempotent.
    - Each project signs in once per serial block, because the login rate limit (5/min per IP and per email)
      stays on.
    - axe (WCAG 2.2 A/AA) runs on every screen in both themes and both viewports.
    - The browser run of the reference question is tagged `@llm` and runs with `make e2e-agent`.

## Alternatives considered
- **Access token in `localStorage`:** simpler reloads, but readable by any injected script. Rejected.
- **A reuse grace window on the server instead of `keepalive`:** it would also let a thief racing the real
  client within the window keep a session. Rejected while the client-side fix suffices.
- **Copying data into dashboard items:** robust to run deletion, but duplicates result sets and loses the link
  to the run's timeline and SQL.
- **TanStack Table v8:** familiar API, but v9 is the current release. We used v9's feature-based API.

## Consequences
- The UI is fully typed against the backend. A route change without `make api-types` fails CI.
- Accessibility regressions (contrast, names, keyboard-scrollable regions) fail `make e2e`. axe found four
  real issues during QA, all fixed:
  - ghosted timeline steps below AA contrast;
  - the account button's name not matching its visible initials;
  - a scrollable rail that was not focusable;
  - `#main` not keyboard-scrollable on the Connections page.
