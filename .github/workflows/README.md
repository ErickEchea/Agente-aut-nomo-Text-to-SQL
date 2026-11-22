# CI workflows

| Workflow | When | What |
|---|---|---|
| [`ci.yml`](ci.yml) | Every push to `main` and every pull request | Backend: ruff, mypy `--strict`, unit + security + integration tests (Testcontainers), 85 % coverage gate. Frontend: ESLint, `tsc`, OpenAPI types in sync, Vitest, build. Security audit: pip-audit, npm audit, gitleaks over the full history. Images: build all three, Trivy (fixable HIGH/CRITICAL fail), compose config. |
| [`stack.yml`](stack.yml) | Pushes to `main` that touch code, weekly, on demand | `make up` on the CPU profile, then Playwright on every screen (axe WCAG 2.2 AA, both themes, 1280/375 px) and the benchmark CI subset with its accuracy gate. |

Dependabot ([`../dependabot.yml`](../dependabot.yml)) proposes weekly updates for uv, npm, GitHub Actions,
Dockerfiles and the compose images. The tools the audit uses are pinned in the [Makefile](../../Makefile)
(`audit*` targets), so CI and a developer machine run exactly the same checks.
