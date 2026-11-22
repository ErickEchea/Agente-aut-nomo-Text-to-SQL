# Security policy

## Reporting a vulnerability
Please report vulnerabilities privately through GitHub: on this repository open **Security → Report a
vulnerability**. Do not open a public issue for a security problem.

Include what you found, how to reproduce it (a question, a request or a SQL string is ideal) and the impact
you expect. You should get an acknowledgement within a week.

## Supported versions
Only the latest commit on `main` is supported.

## Security model in short
NEXUS AI turns questions into SQL with a local LLM. That SQL is treated as untrusted:
- **SQL.** It runs only after an AST validator **and** on a read-only role inside a read-only transaction.
  Each layer blocks writes on its own ([ADR-0005](docs/adr/0005-sql-safety-defense-in-depth.md),
  [ADR-0013](docs/adr/0013-multi-database-read-only-execution.md)).
- **Prompts.** Database values and user text reach the LLM only inside delimited data blocks, and every
  model output is validated before use.
- **Accounts.** Argon2id passwords, short-lived JWTs, rotated refresh cookies with reuse detection, RBAC
  checked against the database, and rate limits
  ([ADR-0010](docs/adr/0010-authentication-and-authorization.md),
  [ADR-0011](docs/adr/0011-rate-limiting.md)).
- **Containers.** nginx is the only ingress. Containers drop all Linux capabilities (PostgreSQL keeps
  five for its entrypoint), cannot gain privileges, and stateless ones have read-only root filesystems
  ([ADR-0023](docs/adr/0023-hardening-and-supply-chain.md)).
- **Supply chain.** Dependencies, the git history and the images are audited in CI with pinned tools
  (`make audit`), and GitHub Actions are pinned by commit SHA.

The latest review, its findings and the accepted residual risks are in
[docs/security-review.md](docs/security-review.md). The stack serves plain HTTP on loopback. Before exposing
it on a network, put a TLS terminator in front of nginx, set `NEXUS_COOKIE_SECURE=true` and add HSTS there.
