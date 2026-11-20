-- Demo (target) database roles — ADR-0005 layer B and ADR-0006.
-- retail_owner: owns and loads the data (seed job only). nexus_reader: the agent's SELECT-only role.

CREATE ROLE retail_owner LOGIN PASSWORD :'owner_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE nexus_reader LOGIN PASSWORD :'reader_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 20;

CREATE DATABASE retail OWNER retail_owner ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE retail FROM PUBLIC;
GRANT CONNECT ON DATABASE retail TO nexus_reader;
-- PUBLIC can connect to the maintenance databases by default; the agent role has no business there.
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;

\connect retail

-- Nobody but the owner may create objects; the reader only sees schema `retail`.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA retail AUTHORIZATION retail_owner;
GRANT USAGE ON SCHEMA retail TO nexus_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE retail_owner IN SCHEMA retail GRANT SELECT ON TABLES TO nexus_reader;

-- Functions that a read-only analyst never needs and that enable DoS or session tampering.
REVOKE EXECUTE ON FUNCTION pg_sleep(double precision) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_sleep_for(interval) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_sleep_until(timestamp with time zone) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION set_config(text, text, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_terminate_backend(integer, bigint) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_cancel_backend(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_config(text, text, boolean) TO retail_owner;

-- Session defaults for the reader (each also enforced per transaction by the executor, ADR-0005 layer C).
ALTER ROLE nexus_reader IN DATABASE retail SET default_transaction_read_only = on;
ALTER ROLE nexus_reader SET statement_timeout = '15s';
ALTER ROLE nexus_reader SET lock_timeout = '2s';
ALTER ROLE nexus_reader SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE nexus_reader SET search_path = retail;
ALTER ROLE retail_owner SET search_path = retail;
