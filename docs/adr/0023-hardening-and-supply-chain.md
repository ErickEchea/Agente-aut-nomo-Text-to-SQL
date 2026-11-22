# ADR-0023: Hardening, single ingress and a pinned supply-chain audit

- Status: Accepted
- Date: 2026-11-22

## Context
Phase 7 reviewed the whole system for security before calling it done: the code, the containers, the
dependencies and the CI. The review and its evidence are in [docs/security-review.md](../security-review.md).
It found no flaw in the controls the earlier ADRs define (SQL validation, read-only roles, auth, rate limits,
credential encryption). It did find gaps around them:

- **Two ways in.** The backend port (8000) was published on the host's loopback next to nginx (8080).
  uvicorn trusts `X-Forwarded-For` from any peer (`--forwarded-allow-ips *`) because nginx overwrites the
  header. A process on the host could talk to 8000 directly and pick its own rate-limit key.
- **Default container privileges.** Every container ran with Docker's default Linux capabilities and could
  gain privileges through setuid binaries. nginx's master process ran as root. The root filesystems were
  writable.
- **Vulnerable OS packages in images.** The base images, even freshly pulled, still shipped a HIGH `zlib`
  CVE (Debian) and a HIGH `libxml2` CVE (Alpine). Debian and Alpine had already published the fixes.
- **`pip` inside the backend image.** The runtime never installs packages, yet the base image's `pip`
  vendors old `urllib3`, `msgpack` and `setuptools`, which carry HIGH CVEs.
- **Connection targets.** An admin can register a data source on any host. Nothing stopped one from
  pointing at NEXUS's own application database, at the Ollama API, or at link-local addresses such as a
  cloud metadata service. The connection test can then probe those addresses.
- **Mutable CI dependencies.** The GitHub Actions were referenced by tags. GHSA-69fq-xp46-6x23 (March 2026)
  showed what that allows: Trivy's own actions had their tags repointed to malicious code.
- **No audit gate and no end-to-end CI.** Nothing in CI checked dependencies, the git history or the
  images. Playwright only ran on the developer machine.

## Decision

### 1. One way in: nginx
- The backend publishes no port. nginx (`:8080`) is the only ingress, so the `X-Forwarded-For` that uvicorn
  trusts is always the one nginx wrote.
- Development tools go through it too:
  - the Vite dev server proxies `/api` to `127.0.0.1:8080`;
  - `/api/docs` is served there when `NEXUS_ENV` is not `production`.
- Removed: `NEXUS_API_PORT`.

### 2. Least-privilege containers (`docker-compose.yml`)

| Service | User | Capabilities | `no-new-privileges` | Root filesystem |
|---|---|---|---|---|
| backend, migrate, demo-seed | `nexus` (uid 999) | none | yes | read-only, `/tmp` tmpfs |
| frontend (nginx) | `nginx` (uid 101) | none | yes | read-only, `/tmp` tmpfs |
| app-db, demo-db | root → `postgres` | `CHOWN DAC_OVERRIDE FOWNER SETGID SETUID` (entrypoint only) | yes | writable (data dir) |
| ollama, ollama-init | root (image default) | none | yes | writable (model store) |
| demo-extensions, k6 | image default | none | yes | read-only |

- nginx runs unprivileged on the official image:
  - the root-only `user` directive is removed;
  - the pid file and temp paths move to `/tmp`;
  - it listens on 8080.
  We did not switch to the `nginx-unprivileged` image, because it lagged a patch release behind
  (1.30.6 against 1.30.7).
- Verified:
  - every running container reports `CapEff: 0` and `NoNewPrivs: 1`;
  - a fresh PostgreSQL initialization works with the five capabilities;
  - Ollama still runs 100 % on the GPU without any capability.

### 3. Patched images
- Each image we build applies the OS security updates at build time:
  - `apt-get upgrade` on Debian;
  - `apk upgrade` on Alpine.
- The demo database holds the PostgreSQL packages first, so the server stays the version its tag names.
  The PGDG repository is enabled, so a plain upgrade would raise the server's minor version.
- The backend runtime uninstalls `pip`.

### 4. Data-source targets (`nexus.datasources.targets`)
Before any driver connects, during a connection test, on create and whenever a stored source is opened,
the host is resolved and refused when it meets any of these:
- **Forbidden range.** Any address is link-local (cloud metadata), multicast, unspecified or reserved.
  Loopback is allowed: a database on the same host is a legitimate source in development.
  IPv4-mapped IPv6 addresses are checked as IPv4.
- **Internal service.** Its address and port match one of the stack's own services: the app database or
  Ollama. These come from the settings, so the check follows configuration changes.

The port is part of the match: Testcontainers publish every database on `localhost`, and only the app
database's own port is refused there.

Residual risk:
- **DNS rebinding.** The driver resolves the name again when it connects, so a record that changes
  between the check and the connection is not covered.
- **Primary control.** Database credentials remain the primary control. Registering connections stays
  admin-only.

### 5. A pinned, reproducible audit (`make audit`, CI)

| Target | Tool | Gate |
|---|---|---|
| `audit-deps` | pip-audit 2.10.1 on `uv export --frozen`; `npm audit` | any known vulnerability (Python); npm `high` or above |
| `audit-secrets` | gitleaks 8.30.1 (image by digest) over the full history | any finding |
| `audit-images` | Trivy 0.76.2 (image by digest) on backend, frontend, demo-db | HIGH/CRITICAL with a fix available |

- **Same targets everywhere.** CI runs exactly these `make` targets, so a developer machine and CI check
  the same things with the same versions.
- **Trivy runs from its container image pinned by digest,** not through `trivy-action`. That is the action
  whose tags were compromised.
- **`gosu` is skipped in the PostgreSQL image.** It is the binary the entrypoint uses to drop privileges.
  It is built with an older Go, and its maintainers document why the standard-library CVEs that scanners
  report in it do not apply.
- **Third-party images are scanned but not gated, because we do not build them.** Their open findings are
  listed in the security review with the reasoning:
  - `pgvector/pgvector` has the same `zlib` CVE;
  - `ollama/ollama` has an `apt` CVE and a `golang.org/x/net` CVE that upstream has not bumped yet.
  Both images are only reachable inside the compose network or on loopback.
- **GitHub Actions are pinned by commit SHA,** with the version kept as a comment.
- **Dependabot proposes weekly updates for uv, npm, actions, Dockerfiles and compose images:**
  - with a 7-day cooldown, so a freshly published, possibly compromised release is never proposed on day
    one;
  - security updates are not delayed.
- **Ollama stays at the version the benchmark measured.** Moving it requires `make bench`.

### 6. End-to-end CI and a load sanity check
- **`stack.yml`** replaces the benchmark-only workflow. On one `make up` (CPU profile) it runs
  Playwright on every screen (axe, both themes, 1280/375 px, SQLite source lifecycle) and then the
  benchmark subset with its gate.
- **`make load`** runs k6 inside the compose network, through nginx, with thresholds. It answers two
  questions:
  - does browsing stay fast while the agent works?
  - do concurrent questions complete when they queue on one GPU?

  It is a sanity check, not a capacity claim: one replica, one GPU, `OLLAMA_NUM_PARALLEL=1`. The results
  are in [docs/load-test.md](../load-test.md).

## Consequences
- **Upgrade path.** After pulling this change, `make up` rebuilds all three images. Anyone using
  `localhost:8000` must switch to `localhost:8080/api`.
- **Builds and drift.** Builds take a little longer (OS upgrades). Images are no longer bit-for-bit
  reproducible from the Dockerfile alone. The Trivy gate in CI catches a regression either way.
- **New variable.** `NEXUS_LOAD_PASSWORD` is added; `make env` appends it to existing `.env` files.
- **What remains.** Single-replica assumptions are unchanged (ADR-0009, ADR-0011), as are the residual
  risks in section 4. All of them are listed in the security review.
