-- Extensions of the demo database. Idempotent: runs on first init and on every `make up`.
-- HypoPG lets the optimizer plan with hypothetical indexes (nothing is written, ADR-0020).
-- Its functions live in their own schema, outside the agent's allow-listed `retail` schema, so
-- LLM-written SQL cannot reach them (the AST validator also denies them by name).
CREATE SCHEMA IF NOT EXISTS hypopg;
CREATE EXTENSION IF NOT EXISTS hypopg WITH SCHEMA hypopg;
GRANT USAGE ON SCHEMA hypopg TO nexus_reader;
