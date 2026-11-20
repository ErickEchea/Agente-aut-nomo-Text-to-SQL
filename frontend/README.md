# frontend

React 19 + TypeScript (strict) + Vite 8, Tailwind v4 design tokens, shadcn/ui, Motion, TanStack, ECharts.
See [ADR-0016](../docs/adr/0016-frontend-stack-and-design-system.md). Production image: nginx serving the build
and reverse-proxying `/api` to the backend (SSE-safe: buffering off).

Phase 1 ships a real status page (live `/api/health/ready`, es/en); the full app arrives in Phase 4.

```bash
npm ci && npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run lint && npm run typecheck && npm run test && npm run build
```
