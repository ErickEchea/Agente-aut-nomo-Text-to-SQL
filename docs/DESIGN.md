# NEXUS AI — Design system

The UI is an **intelligence command center**: a calm, dark operations surface where the data and the agent's
reasoning are the only loud things. It must feel like a precise instrument, not a chat toy and not a generic
admin template.

Tokens are the single source of truth (`frontend/src/styles/tokens.css`). Components never use raw colors; a
unit test (`src/styles/tokens.test.ts`) fails on any hex literal outside the token files and verifies WCAG AA
contrast for every text/surface pair below.

## 1. Principles

1. **Signal over chrome.** Hairline borders, recessive surfaces, one accent. Color is spent on state (agent
   running, failed, repaired) and on data, never on decoration. No gradients on surfaces, no purple.
2. **Show the work.** The agent timeline is the signature element: every step is visible, timed and
   inspectable. Assumptions and repairs are first-class, not hidden in logs.
3. **Numbers are typography.** Figures and SQL are set in a monospace with tabular digits so columns align and
   values scan like an instrument readout.
4. **Hierarchy, not a wall of cards.** One hero answer per view, then supporting detail. Cards differ in size
   and weight according to importance.
5. **Accessible by construction.** WCAG 2.2 AA contrast, visible focus, full keyboard operation,
   `prefers-reduced-motion` respected, responsive from 375 px.

## 2. Color

Dark is the default; light mode is a *selected* palette, not an inversion. The theme is applied with
`data-theme="dark|light"` on `<html>`; "system" follows `prefers-color-scheme`.

| Token | Dark | Light | Use |
|---|---|---|---|
| `bg` | `#0a0d10` | `#f3f5f7` | Page canvas (with a faint 24 px dot grid on the workspace) |
| `surface-1` | `#12161b` | `#ffffff` | Panels, cards, chart surface |
| `surface-2` | `#181d23` | `#f7f8fa` | Inputs, popovers, table header |
| `surface-3` | `#212831` | `#eceff3` | Hover, selected row, pressed |
| `line` | `#262d36` | `#dfe3e8` | Hairline borders, gridlines |
| `line-strong` | `#3a4450` | `#c3cad3` | Input borders, dividers that must be seen |
| `fg` | `#eef2f5` | `#0d1216` | Primary text |
| `fg-secondary` | `#b3bcc7` | `#434c57` | Secondary text |
| `fg-muted` | `#8a95a3` | `#5d6773` | Labels, captions, axis text |
| `accent` | `#3fd0c9` | `#08716c` | Primary action, focus ring, active agent step |
| `accent-strong` | `#72e2dc` | `#075f5b` | Accent hover / pressed |
| `accent-ink` | `#04201e` | `#ffffff` | Text on an accent fill |
| `success` | `#4ad27f` | `#1b7a41` | Completed step, verified, "ok" |
| `warning` | `#f2b53a` | `#8f5d00` | Assumption, repair in progress, truncated |
| `danger` | `#ff7070` | `#bf2f2f` | Failed step, rejected SQL, destructive action |
| `info` | `#73aaff` | `#2456b3` | Informational notes |

Each signal color also has a `*-soft` variant (the color at 12–14 % alpha) for backgrounds such as badges and
the SQL diff (`success-soft` = added line, `danger-soft` = removed line). A signal color is never the only
carrier of meaning: it is always paired with an icon and a label.

### Data colors

Charts use eight categorical slots validated with the dataviz method (OKLab ΔE, Machado CVD simulation),
in fixed order, never cycled. A single series uses slot 1 only (no legend); more than eight series fold
into "Otros".

| Slot | Dark (on `#12161b`) | Light (on `#ffffff`) |
|---|---|---|
| 1 blue | `#3987e5` | `#2a78d6` |
| 2 orange | `#d95926` | `#eb6834` |
| 3 aqua | `#199e70` | `#1baf7a` |
| 4 yellow | `#c98500` | `#eda100` |
| 5 magenta | `#d55181` | `#e87ba4` |
| 6 green | `#0ca30c` | `#008300` |
| 7 violet | `#9085e9` | `#6250d6` |
| 8 red | `#e66767` | `#e34948` |

Validation results:
- Dark: every check passes, with worst adjacent CVD ΔE 8.4 and normal-vision ΔE 19.3. Every slot has ≥ 3:1
  contrast on the chart surface.
- Light: every check passes except a contrast WARN for slots 3, 4 and 5 (< 3:1 on white). The required
  relief is in place: every chart has a Table tab and tooltips with the exact values.

## 3. Typography

| Role | Family | Notes |
|---|---|---|
| Display / headings | **Bricolage Grotesque** (variable) | Characterful grotesque with optical sizing. Page titles, hero answer, empty states |
| Body / UI | **IBM Plex Sans** 400/500/600 | Neutral and technical, with excellent Spanish diacritics |
| Code & figures | **JetBrains Mono** (variable) | SQL, table numbers, KPI values, durations, token counts; `tabular-nums` in columns |

All fonts are self-hosted via Fontsource, as the CSP only allows `font-src 'self'`.

The scale (size/line-height in px):
- display 36/40
- h1 26/32
- h2 19/26
- h3 15/22
- body 14/22
- small 13/20
- micro 11/16, uppercase with +0.08em tracking, used for instrument labels such as `PASO 3 · 412 ms`

## 4. Space, radius, elevation

- **Spacing:** 4 px base (Tailwind's default scale). Panels use 20–24 px padding and dense tables 8–12 px.
- **Radii:** `sm` 4, `md` 8, `lg` 12, `xl` 16. Data marks use 4 px rounded data ends.
- **Elevation:** a single shadow, `shadow-overlay`, used only for floating layers (palette, dialogs,
  popovers). In-page panels are separated by hairlines, not shadows.
- **Focus:** a 2 px `accent` ring with a 2 px offset on every interactive element (`:focus-visible`).

## 5. Motion

| Token | Value | Use |
|---|---|---|
| `duration-fast` | 120 ms | Hover, press |
| `duration-base` | 200 ms | Tabs, expanding a step, toasts |
| `duration-slow` | 360 ms | Page and panel entrances |
| `ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | Entrances |
| `ease-in-out` | `cubic-bezier(0.65, 0, 0.35, 1)` | State changes |

The running agent step shows a soft pulse on its node, and the timeline rail fills as steps complete. Every
animation reads `useReducedMotion()`: with reduced motion, transitions become instant opacity changes and
pulses stop. State is never conveyed by motion alone.

## 6. Layout

- **App shell:** a left navigation rail (collapsed to a bottom sheet menu under 768 px), a top bar with the
  connection badge, the command palette trigger (`Ctrl/⌘ K`), theme and language.
- **Workspace (≥ 1200 px):** two columns. The conversation and results are on the left (fluid). The agent
  timeline is a 380 px rail on the right, sticky while scrolling. Under 1200 px the timeline becomes a
  collapsible panel above the results.
- **Results:** the hero answer (headline + KPI cards) comes first. It is followed by tabs: *Tabla · Gráfico ·
  SQL · Explicación · Optimización*. KPI cards are not identical: the first is the hero (larger figure), the
  rest are compact.

## 7. Components

Primitives live in `src/components/ui` (shadcn/ui pattern on Radix, restyled with tokens): Button (primary,
secondary, ghost, danger; sizes sm/md), Input, Textarea, Tabs, Dialog, DropdownMenu, Tooltip, Badge, Skeleton,
Switch, Toast (sonner).

Domain components:
- **AgentTimeline:** one node per graph step. Each node has an icon, a localized name, status (pending ·
  running · done · failed · repaired), a duration, tokens and expandable output. SQL is highlighted with
  Shiki. A repair shows a red/green unified diff against the previous attempt.
- **DataTable:** TanStack Table + Virtual. Sticky header, sorting, a global filter and CSV export. Numbers are
  right-aligned in the mono font.
- **ChartView:** ECharts with a theme generated at runtime from the tokens, so it follows the theme switch.
  It exports to PNG and shows tooltips on every mark.
- **KpiCard, ExplanationPanel** (headline, bullets, caveats and a "verified figures" badge), **SqlBlock**,
  **SqlDiff**, **EmptyState** (with clickable example questions), **ErrorState** (what happened plus what to
  do next).

## 8. Content

- Spanish by default with English available. All UI strings live in `src/i18n` (ESLint
  `i18next/no-literal-string`).
- Money is in USD with locale-aware formatting: `es-EC` gives `$ 299.672,19` and `en-US` gives `$299,672.19`.
  Dates use the user's locale.
- Errors say what happened and what to do next ("El modelo tardó demasiado. Reintenta o simplifica la
  pregunta.") and never show raw stack traces.
