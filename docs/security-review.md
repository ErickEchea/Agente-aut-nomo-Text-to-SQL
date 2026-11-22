# Security review — Phase 7

- Date: 2026-11-22
- Scope: everything in this repository as of Phase 7:
  - backend (`nexus`), frontend, nginx, `docker-compose.yml`, Dockerfiles;
  - GitHub workflows;
  - the git history.
- Decisions that came out of it: [ADR-0023](adr/0023-hardening-and-supply-chain.md).

## Method
- **Manual review of each trust boundary.** Six boundaries:
  - the browser and the API;
  - the API and the agent;
  - the LLM and the SQL that reaches a database;
  - database contents and the prompt;
  - the admin and the data-source registry;
  - the containers and the host.
- **Automated checks.** Repeatable with `make audit`, and run in CI:
  - pip-audit and `npm audit` on the lockfiles;
  - gitleaks on the full history;
  - Trivy on every image the repository builds;
  - ruff's `S` (bandit) rules on every lint;
  - the SQL attack suite in its three modes (`make test-security`).
- **Runtime verification on the hardened stack.**
  - Each container's effective capabilities, `no-new-privileges` flag and root-filesystem mode.
  - A fresh PostgreSQL initialization with the reduced capabilities.
  - `make e2e` (25 passed, 1 skipped on purpose).
  - `make load`.

## Threat model (summary)

| Asset | Where | Who must not get it |
|---|---|---|
| Business data, including PII columns | demo DB and registered sources | anyone without an account; PII from everyone (masked in results) |
| Accounts: password hashes, refresh tokens | app DB | everyone |
| Credentials of registered sources | app DB (Fernet-encrypted) | everyone; admins see host/user, never the password |
| Audit log, run history | app DB | other users (history), non-admins (audit) |
| Integrity of every connected database | each source | everyone: the agent only reads |

| Actor | Can do |
|---|---|
| Anonymous network client | reach nginx on loopback (the stack binds nothing else publicly) |
| Viewer / analyst / admin | what RBAC allows (ADR-0010) |
| Malicious database content | reach the prompt inside delimited data blocks (prompt injection) |
| Compromised dependency or CI action | run code at build or CI time |
| Process on the host | reach the loopback-published ports |

## Controls checked

| Area | Control | Evidence | Result |
|---|---|---|---|
| SQL execution | AST validator, then a read-only role, then a read-only transaction with timeouts and a row cap; each layer blocks on its own (ADR-0005, ADR-0013) | attack suite in three modes; `nexus_reader` cannot write (integration tests); a sqlglot tokenizer crash fails closed (Phase 6) | ✅ |
| Prompt injection | DB values and user text only inside delimited data blocks; every LLM output is validated (Pydantic, then the SQL validator) | `nexus.agent.prompts`, guards of ADR-0018 | ✅ (residual R7) |
| Passwords | Argon2id (argon2-cffi defaults); at least 12 characters; the same hash cost for unknown emails (no user enumeration by timing) | `nexus.security.passwords`, `accounts.authenticate` | ✅ |
| Access tokens | HS256 with the algorithm fixed server-side; `sub/role/exp/iat/iss/aud/jti` required; 15 min; secret ≥ 32 chars | `nexus.security.tokens`, settings validator | ✅ |
| Refresh tokens | Opaque, stored as SHA-256, rotated on every use, reuse revokes the whole family; cookie `HttpOnly`, `SameSite=Strict`, path `/api/auth` | `accounts.rotate_refresh`, `api/auth.py` | ✅ (`Secure` needs HTTPS, R4) |
| Authorization | The role is read from the DB on every request (demotion is immediate); another user's run returns 404, not 403; connections are admin-only, and network details go to admins only | `api/deps.py`, `api/runs.py`, `api/connections.py` | ✅ |
| Rate limiting | Login per IP and per email (5/min); runs per user (20/min); token buckets with bounded memory | `nexus.security.rate_limit`, ADR-0011 | ✅ after F1 |
| Browser storage | Access token in memory only; `localStorage` holds UI preferences and the selected source | `frontend/src/app/preferences.tsx`, `workspace/session.tsx` | ✅ |
| HTTP headers | CSP `default-src 'self'` with no inline script, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `server_tokens off` | `frontend/nginx.conf` | ✅ (HSTS belongs to the TLS terminator, R4) |
| CORS | Same origin in production (nginx serves the app and `/api`); explicit allowlist otherwise | `main.py` | ✅ |
| Errors and logs | No debug mode; no stack traces to clients; JSON logs with `request_id`; keys such as password, token, secret, cookie and DSN are redacted | `nexus.observability.logging` | ✅ |
| API surface | Interactive docs off in production | `main.py` | ✅ |
| Secrets | Environment only; `make env` generates 32-byte secrets and never overwrites; no secret in the git history | gitleaks (below) | ✅ |
| SQLite sources | Only files inside the configured directory (no traversal or symlink escape), opened `mode=ro`, directory mounted read-only | `registry.resolve_sqlite`, integration test | ✅ |
| Network sources | Write privileges detected from the catalog and acknowledged explicitly; read-only session settings | `registry.probe`, ADR-0013 | ✅ after F4 |
| PII | Configured columns masked in results, samples and prompts | `nexus.security.pii` | ✅ |

## Findings and fixes

| ID | Severity | Finding | Fix | Verified by |
|---|---|---|---|---|
| F1 | Medium | The API port 8000 was published on loopback next to nginx. uvicorn trusts `X-Forwarded-For` from any peer, so a host process could pick its own rate-limit key. | The backend publishes no port; nginx is the only ingress; Vite proxies to it. | `curl 127.0.0.1:8000` gets no connection; e2e and e2e-agent go through 8080 |
| F2 | Medium | Containers ran with Docker's default capabilities, could escalate through setuid binaries, and had writable root filesystems. nginx's master process ran as root. | `cap_drop: ALL`, `no-new-privileges`, read-only root plus a `/tmp` tmpfs for stateless services; five capabilities for the PostgreSQL entrypoint only; nginx as uid 101. | `/proc/1/status`: `CapEff 0`, `NoNewPrivs 1` in every service; fresh DB init; Ollama 100 % GPU |
| F3 | High (CVSS) / low exposure | Fixed OS CVEs not yet in the base images: `zlib` CVE-2026-85091 (Debian) and `libxml2` CVE-2026-86144 (Alpine). `pip` vendored vulnerable `urllib3`, `msgpack` and `setuptools`. | OS security upgrades at build time; `pip` removed from the backend runtime. | Trivy: 0 fixable HIGH/CRITICAL in backend, frontend and demo-db |
| F4 | Medium | A data source could target NEXUS's own app DB or Ollama, or link-local addresses such as cloud metadata, and the connection test could probe them. | `nexus.datasources.targets`: refused by resolved address and port, before any driver connects. | 14 unit tests; integration test registering the real app DB is refused |
| F5 | Medium | GitHub Actions were referenced by mutable tags (see GHSA-69fq-xp46-6x23). | Pinned by commit SHA; Dependabot with a 7-day cooldown. | `ci.yml`, `stack.yml`, `.github/dependabot.yml` |
| F6 | Low | No dependency, secret or image audit in CI. | `make audit-*` targets with pinned tools, run by CI. | CI `audit` and `images` jobs |
| F7 | Low | Playwright and the axe checks never ran in CI. | `stack.yml` runs `make e2e` on the full stack before the benchmark subset. | GitHub Actions run of `stack.yml` |

## Automated results (2026-11-22)

| Check | Result |
|---|---|
| pip-audit 2.10.1 on `backend/uv.lock` (all groups) | No known vulnerabilities |
| `npm audit` on `frontend/package-lock.json` | 0 vulnerabilities |
| gitleaks 8.30.1 over the full history | No leaks |
| Trivy 0.76.2: `nexus-backend`, `nexus-frontend` | 0 fixable HIGH/CRITICAL (after F3) |
| Trivy 0.76.2: `nexus-demo-db` | 0 fixable HIGH/CRITICAL in OS packages; `gosu` skipped (R2) |
| Trivy 0.76.2: `pgvector/pgvector:0.8.7-pg18-trixie` (not built here) | `zlib` CVE-2026-85091; `gosu` stdlib (R2) |
| Trivy 0.76.2: `ollama/ollama:0.40.16` (not built here) | `apt` CVE-2026-109518; `golang.org/x/net` CVE-2026-78661 (R2) |

## Residual and accepted risks

| ID | Risk | Why accepted / mitigation |
|---|---|---|
| R1 | Single replica | The rate limiter, the concurrent-run lock and SSE fan-out live in process (ADR-0009, ADR-0011). Scaling out needs a shared store first. |
| R2 | Findings in images not built here | **pgvector:** the `zlib` fix exists in Debian, but upstream has not rebuilt the image; the app DB is reachable only in the compose network and on loopback, and Dependabot proposes the rebuilt image. **Ollama:** `apt` is not used at runtime; `golang.org/x/net` is still v0.61.0 on Ollama's `main`. Ollama stays at the version the benchmark measured and is not exposed beyond loopback. **gosu:** it runs only in the entrypoint, to drop privileges, and its maintainers document why the stdlib CVEs do not apply. |
| R3 | DNS rebinding against F4 | The driver resolves the name again when it connects. Admin-only feature; the credentials stay the primary control. |
| R4 | Plain HTTP | The stack binds loopback only. Exposing it needs a TLS terminator in front of nginx, `NEXUS_COOKIE_SECURE=true` and HSTS at that terminator. |
| R5 | Login throttling per email | Anyone can slow a known user's logins to 5 attempts per minute. This is the intended trade-off against password guessing (ADR-0011). |
| R6 | Trusted admins | Admins register sources (they need valid credentials), read the audit log and see network details. Admin accounts are created only from the CLI or at bootstrap. |
| R7 | Prompt injection within read-only bounds | Text stored in a database could steer the generated SQL. That SQL still passes the validator and runs read-only, on allowed tables, with PII masked. It can produce a wrong answer, not a write or an exfiltration of masked columns. The SQL and its clause-by-clause explanation are always shown. |
| R8 | Wrong but valid answers | Execution accuracy is 71.4 % (ADR-0022). This is an integrity risk for decisions, not a security flaw. Answers are grounded in the result rows and show their SQL. |
| R9 | Source maps in the production bundle | The code is open source; the maps help debugging. Nothing secret is bundled (secrets never reach the frontend). |

## How to repeat this review
```bash
make up            # hardened stack
make audit         # pip-audit, npm audit, gitleaks, Trivy (pinned versions)
make test-security # SQL attack suite, three modes
make e2e           # every screen with axe, through nginx
make load          # k6 sanity check -> docs/load-test.md
```
