# ADR-0016 — Frontend stack and design system

- Status: Accepted
- Date: 2026-11-20

## Decision
- React 19 + TypeScript 6 (strict, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) + Vite 8.
- **Design tokens first** (`frontend/src/styles/tokens.css`): color (semantic layers: `bg`, `surface-1..3`,
  `border`, `text-primary/secondary/muted`, `accent`, `signal-success/warning/danger/info`, `data-1..8`),
  typography, spacing (4 px base), radii, shadows/elevation, motion (durations + easings). Dark is default,
  light via `[data-theme="light"]`. Tailwind v4 `@theme` maps utilities to these variables; the ECharts theme is
  generated from the same tokens at runtime so charts follow theme switches. Documented in `docs/DESIGN.md`.
- shadcn/ui components are copied into `src/components/ui` and restyled with the tokens (no default look).
- Server state: TanStack Query. Routing: React Router 8. Results grid: TanStack Table + Virtual.
  Command palette: `cmdk`. SQL highlighting: Shiki (fine-grained bundle with only the SQL grammar).
  Diff: `diff` (jsdiff) rendered as a unified red/green view.
- Motion: `motion` (Framer Motion); every animation reads a `useReducedMotion` gate.
- i18n: i18next with `es` (default) and `en` namespaces; no hard-coded UI strings (ESLint rule).
- Accessibility: WCAG 2.2 AA contrast verified by a token-level test; axe checks in Playwright; full keyboard
  navigation; responsive from 375 px.
- Visual QA: Playwright screenshots of every screen in dark/light × desktop/mobile reviewed before closing Phase 4.

## Alternatives considered
- Next.js: SSR is unnecessary for an authenticated internal tool and complicates SSE through the dev server.
- Recharts/visx: ECharts was mandated and is stronger for dense, exportable charts.
