#!/bin/sh
# Runs once, on first initialization of the app-db volume.
set -eu
: "${NEXUS_APP_DB_PASSWORD:?NEXUS_APP_DB_PASSWORD is required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_pw="$NEXUS_APP_DB_PASSWORD" \
  -f /docker-entrypoint-initdb.d/sql/app-init.sql
