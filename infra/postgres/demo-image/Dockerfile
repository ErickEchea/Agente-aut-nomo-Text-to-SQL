# Demo (target) database: PostgreSQL 18 + HypoPG, so the optimizer can measure an index before anyone
# creates it (hypothetical indexes live in backend memory; nothing is written). Phase 5, ADR-0020.
FROM postgres:18.7-trixie
# OS security fixes published after the base image was built (scanned in CI with Trivy). PostgreSQL
# itself is held: the server version stays the one the tag names (the PGDG repository is enabled).
RUN apt-get update \
 && apt-mark hold $(dpkg-query -W -f '${db:Status-Status} ${Package}\n' 'postgresql*' 'libpq*' \
      | awk '$1 == "installed" { print $2 }') \
 && apt-get -y upgrade \
 && apt-get install -y --no-install-recommends postgresql-18-hypopg=1.4.5-1.pgdg13+2 \
 && rm -rf /var/lib/apt/lists/*
