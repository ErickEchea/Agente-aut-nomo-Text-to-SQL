#!/bin/sh
# Runs once, on first initialization of the demo-db volume (after 10-roles.sh created `retail`).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname retail \
  -f /docker-entrypoint-initdb.d/sql/demo-extensions.sql
