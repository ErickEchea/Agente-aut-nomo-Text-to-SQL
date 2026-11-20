#!/bin/sh
# Runs once, on first initialization of the demo-db volume (docker-entrypoint-initdb.d).
set -eu
: "${NEXUS_DEMO_OWNER_PASSWORD:?NEXUS_DEMO_OWNER_PASSWORD is required}"
: "${NEXUS_DEMO_READER_PASSWORD:?NEXUS_DEMO_READER_PASSWORD is required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$NEXUS_DEMO_OWNER_PASSWORD" \
  -v reader_pw="$NEXUS_DEMO_READER_PASSWORD" \
  -f /docker-entrypoint-initdb.d/sql/demo-roles.sql
