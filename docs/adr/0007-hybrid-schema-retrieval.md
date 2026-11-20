# ADR-0007 — Hybrid schema retrieval and embedding model

- Status: Accepted (embedding model confirmed by retrieval eval in Phase 3)
- Date: 2026-11-20

## Context
Sending the full schema to a 7–8B model wastes context and hurts accuracy. Questions are in Spanish and use
business vocabulary ("ingresos", "más vendidos") that may not appear in identifiers; identifiers may be
abbreviated. We need both semantic and lexical matching, plus the join path between selected tables.

## Decision
- **Documents** (table `schema_documents`, one row each): table (name + comment + columns summary), column
  (table.column, type, comment, up to N distinct sample values, PII-masked), foreign key, glossary term
  (`data/glossary.yaml`, versioned), verified example (question → SQL).
- **Dense**: Ollama embeddings into `vector(dim)` with an HNSW index (cosine).
- **Lexical**: `tsvector` with a `spanish` config over `unaccent`ed text (GIN), plus `pg_trgm` similarity on
  identifiers for typos/abbreviations.
- **Fusion**: Reciprocal Rank Fusion (k = 60) of dense and lexical rankings, then per-type quotas
  (tables, columns, glossary, examples).
- **Join path**: build the FK graph from introspection; connect selected tables with a minimum Steiner-tree
  approximation (shortest paths between terminals), adding bridge tables (e.g. `detalle_ventas` between `productos`
  and `ventas`). Output is the sub-schema DDL with comments and the explicit join conditions.
- **Embedding model**: start with `qwen3-embedding:0.6b` (multilingual, small VRAM footprint); compare against
  `embeddinggemma-2` on recall@5 of gold tables derived from the golden set. Store the model name + dimension
  per index; changing it triggers re-indexing.

## Alternatives considered
- Dense only: misses exact identifier matches and codes.
- A separate vector DB (Qdrant, Chroma): extra service; pgvector keeps transactional consistency with app data.
- LLM-based table selection: slower and less reproducible; used only as a tie-breaker if recall is insufficient.

## Consequences
- Indexing a connection costs one embedding call per document (batched); progress is shown in the UI.
- Retrieval is benchmarked separately, so regressions are attributable.
