# Demo (target) database: PostgreSQL 18 + HypoPG, so the optimizer can measure an index before anyone
# creates it (hypothetical indexes live in backend memory; nothing is written). Phase 5, ADR-0020.
FROM postgres:18.7-trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-18-hypopg=1.4.5-1.pgdg13+2 \
 && rm -rf /var/lib/apt/lists/*
