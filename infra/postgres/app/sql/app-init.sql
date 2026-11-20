-- App database: owned by the non-superuser role the API uses (ADR-0006).
CREATE ROLE nexus_app LOGIN PASSWORD :'app_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE nexus_app OWNER nexus_app ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE nexus_app FROM PUBLIC;

\connect nexus_app

-- Extensions need superuser to install; the app role then uses them.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO nexus_app;
