# NEXUS AI — Architecture

> Status: Phase 0 (design). Every decision referenced here has an ADR in [`docs/adr/`](adr/).
> Diagrams are Mermaid; GitHub renders them natively.

## 1. Goals and non-goals

**Goals**
- Answer natural-language business questions (Spanish first, English supported) over relational data with
  verifiable SQL, results, charts and an executive summary.
- Run fully local: no paid APIs. LLM and embeddings are served by Ollama.
- Never execute unsafe SQL. Safety is layered so that **each layer is sufficient on its own**.
- Make the agent's reasoning observable: every graph node streams its lifecycle to the UI over SSE.
- Measure quality with a reproducible benchmark (execution accuracy) that also picks the default model.

**Non-goals (v1)**
- Write access to target databases (the product is strictly read-only).
- Horizontal scaling of the API (single replica; see ADR-0011 for the rate-limit implication).
- Fine-tuning models.

## 2. System context

```mermaid
flowchart LR
    user([Business user<br/>admin · analyst · viewer])
    subgraph nexus[NEXUS AI]
        fe[Web app<br/>React + Vite]
        api[API + Agent<br/>FastAPI + LangGraph]
    end
    ollama[(Ollama<br/>LLM + embeddings)]
    appdb[(App DB<br/>PostgreSQL + pgvector)]
    demo[(Retail demo DB<br/>PostgreSQL)]
    ext[(User-registered sources<br/>PostgreSQL · MySQL · SQLite)]

    user -->|HTTPS| fe
    fe -->|REST + SSE| api
    api -->|HTTP| ollama
    api -->|read/write, app role| appdb
    api -->|read-only role| demo
    api -->|read-only credentials| ext
```

## 3. Containers (Docker Compose)

```mermaid
flowchart TB
    subgraph host[Developer machine / server]
        subgraph net[compose network: nexus]
            frontend[frontend<br/>nginx serving Vite build<br/>:8080]
            backend[backend<br/>uvicorn FastAPI<br/>:8000]
            appdb[(app-db<br/>pgvector/pgvector:pg18<br/>nexus_app)]
            demodb[(demo-db<br/>postgres:18 + HypoPG<br/>retail)]
            ext[demo-extensions<br/>one-shot: HypoPG in schema hypopg]
            sqlite[/data/sqlite<br/>read-only mount<br/>SQLite sources/]
            ollama[ollama<br/>ollama/ollama<br/>GPU or CPU profile]
            init[ollama-init<br/>one-shot: pull models]
            seed[demo-seed<br/>one-shot: generate + load retail data]
        end
    end
    frontend -->|/api reverse proxy| backend
    backend --> appdb
    backend --> demodb
    backend --> ollama
    init --> ollama
    seed --> demodb
    ext --> demodb
    backend -.-> sqlite
    backend -.->|registered sources| extdb[(Your PostgreSQL / MySQL)]
```

- Host ports avoid the defaults already in use on the dev machine (5432, 11434): app-db `55432`,
  demo-db `55433`, API `8000`, web `8080`. Ollama is **not** published to the host by default.
- Healthchecks: `pg_isready` for both databases, `/api/health/ready` for the backend (checks DBs + Ollama + models
  present), HTTP 200 for the frontend. `depends_on: condition: service_healthy|service_completed_successfully`.
- GPU is an override file (`docker-compose.gpu.yml`) selected by `make up` when `nvidia-smi` is available.
  The CPU profile swaps the default model for a smaller one (ADR-0003).
- The demo DB lives in its **own container** so the agent treats it exactly like any external source:
  separate credentials, separate pool, no network path to app tables (ADR-0006).

## 4. Backend module map

```
backend/src/nexus/
├── api/            FastAPI routers, dependencies, SSE transport, error mapping
├── agent/          LangGraph graph, typed state, one module per node, prompt templates
│   └── temporal/   deterministic relative-date resolver (es/en)
├── llm/            LLMProvider protocol + Ollama implementation, structured-output helper
├── rag/            schema introspection, document builder, embeddings, hybrid retriever, join-path finder
├── sql/            SQLGlot validator, per-engine read-only executor, clause annotation, plan optimizer
├── bench/          golden set, execution-accuracy comparison, runner, metrics, report (nexus-bench)
├── security/       JWT, password hashing, RBAC, rate limiting, credential encryption, PII masking, audit
├── memory/         short-term (conversation) and long-term (preferences, verified examples, corrections)
├── datasources/    dialect profiles, credential cipher, introspection, connection registry + probe
├── observability/  structlog config, request_id middleware, per-node trace spans
├── db/             SQLAlchemy models for the app DB + Alembic migrations
└── config.py       pydantic-settings, single source of configuration
```

Dependency rule: `api → agent → (llm, rag, sql, memory) → db`. `security` and `observability` are
cross-cutting and may be imported anywhere; nothing imports `api`.

## 5. Agent graph (LangGraph)

```mermaid
flowchart TD
    start([question + conversation_id]) --> understand
    understand -->|out_of_scope| refuse[respond: out of scope] --> done
    understand -->|ambiguous| clarify[respond: clarification<br/>with concrete options] --> done
    understand -->|data / follow_up| retrieve_schema
    retrieve_schema --> plan
    plan --> resolve_time
    resolve_time --> generate_sql
    generate_sql --> validate
    validate -->|rejected, attempts < 3| repair
    validate -->|rejected, attempts = 3| fail[respond: actionable error] --> done
    validate -->|ok| execute
    execute -->|db error, attempts < 3| repair
    execute -->|db error, attempts = 3| fail
    execute -->|rows| verify_results
    verify_results -->|suspicious, attempts < 3| repair
    verify_results -->|ok or budget exhausted<br/>with warning| next_step{more plan steps?}
    repair --> validate
    next_step -->|yes| generate_sql
    next_step -->|no| visualize
    visualize --> explain
    explain -->|ungrounded, ≤2x| explain
    explain --> remember
    remember --> done([final answer])
```

### Node contracts

| Node | Input (from state) | Output (to state) | LLM? |
|---|---|---|---|
| `understand` | question, short-term memory | `intent ∈ {data, follow_up, ambiguous, out_of_scope}`, rewritten standalone question, clarification options | yes (structured) |
| `retrieve_schema` | standalone question | ranked sub-schema (tables, columns, comments, sample values), join path, glossary hits, verified few-shot examples | embeddings only |
| `plan` | question, sub-schema | `steps[]` (1..n) and strategy `single_cte | multi_query` | yes (structured) |
| `resolve_time` | question, connection `as_of` date | concrete `[start, end)` ranges + human-readable assumptions | **no** (pure Python) |
| `generate_sql` | step, sub-schema, time ranges, examples, glossary | `SqlCandidate{sql, dialect, tables_used, assumptions, rationale}` | yes (structured) |
| `validate` | candidate, allowlists | normalized SQL with enforced `LIMIT`, or `ValidationError(code, detail)` | no |
| `execute` | validated SQL, connection | rows, columns, row count, duration, or `DbError(sqlstate, message)` | no |
| `repair` | previous SQL, error, sub-schema | new candidate; attempt appended to `attempts[]` (diffed in UI) | yes (structured) |
| `verify_results` | rows, step, time ranges | `ok` or recoverable issue (empty set, unexpected NULLs, shape mismatch) | rules + yes |
| `visualize` | columns, rows (sample), question | ECharts option validated against a JSON schema | rules + yes |
| `explain` | results, assumptions | executive summary whose every number is grounded in the result set | yes (structured) |
| `remember` | full run | persisted run, conversation turn, frequency stats | no |

### State (abridged)

```python
class AgentState(TypedDict):
    run_id: UUID; user_id: UUID; connection_id: UUID; conversation_id: UUID
    question: str; standalone_question: str; locale: Literal["es", "en"]
    intent: Intent; clarification: Clarification | None
    schema_context: SchemaContext; plan: Plan; time_ranges: list[ResolvedRange]
    current_step: int; step_results: list[StepResult]
    attempts: Annotated[list[SqlAttempt], operator.add]   # every try, for the diff view
    chart: ChartSpec | None; summary: Summary | None
    assumptions: Annotated[list[Assumption], operator.add]
    usage: Annotated[list[TokenUsage], operator.add]
```

### Streaming protocol

`POST /api/runs` → `201 {run_id}`. `GET /api/runs/{run_id}/events` → `text/event-stream`.
Events are persisted (`run_events`) before being sent, so a reconnect with `Last-Event-ID` replays them.

```
event: node.started   data: {"node":"generate_sql","step":1,"attempt":1,"ts":"…"}
event: node.token     data: {"node":"explain","delta":"Las ventas…"}           (optional, explain only)
event: node.completed data: {"node":"generate_sql","duration_ms":812,
                             "tokens":{"prompt":1834,"completion":121},"output":{…summarized…}}
event: node.failed    data: {"node":"execute","error":{"sqlstate":"42703","message":"…"}}
event: run.completed  data: {"run_id":"…","status":"answered|clarification|refused|failed"}
```

The frontend consumes the stream with `fetch` + `ReadableStream` (not `EventSource`, which cannot send the
`Authorization` header), so auth stays header-based.

### Implementation status (Phase 6)
- `nexus.bench` measures the agent end to end on the golden set (ADR-0015, ADR-0022).
  - It builds each question's context with `SourceRuntime.agent_context()`, the same call the API uses.
  - Per-node model routing is configuration (`NEXUS_AGENT__MODELS__*`), and `NEXUS_OLLAMA__THINK`
    turns off the reasoning phase of models that think by default.
  - Results go to `bench/results/*.json`, the app DB (`benchmark_runs`, `benchmark_results`) for the
    Benchmark page, and `docs/benchmark.md`.

### Implementation status (Phase 5)
- Every run is bound to a **data source** (`connection_key`). `ConnectionRegistry` builds one runtime
  per source: engine, executor, catalog, validator policy, masker, retriever and samples. The graph is
  the same for every engine; prompts receive the source's `DialectProfile` (ADR-0013).
- Two read-only views explain each answered step, and neither calls the LLM (ADR-0021):
  - `nexus.sql.annotate` explains the SQL clause by clause, with character spans.
  - `nexus.sql.optimizer` reads `EXPLAIN` output and suggests indexes. On PostgreSQL it measures each
    suggestion with HypoPG hypothetical indexes.
- If the grounded `explain` step falls back, the summary is now a readable sentence in the user's
  locale.

### Implementation status (Phase 4)
Two deterministic guards were added after the live browser QA (ADR-0020):
- `plan` discards a plan whose steps are SQL and falls back to the standalone question.
- `visualize` never plots identifier columns, and prefers the measure the question names.
`GET /api/runs/{id}` returns a typed `RunResult`.

### Implementation status (Phase 3)
All nodes in the diagram are implemented. `retrieve_schema` runs hybrid retrieval and sends about 4.5 of 10
tables plus join hints. `visualize` produces validated ECharts specs or KPI cards. `explain` produces a
grounded summary in the user's locale. `remember` updates long-term memory. Measured choices: ADR-0019.

### Implementation status (Phase 2)
Implemented: `understand` (deterministic guard first, ADR-0018), `plan`, `resolve_time`, `generate_sql`,
`validate`, `execute`, `repair`, `verify_results` (date filters, empty/NULL results, glossary `requires`) and a
deterministic `respond`. `retrieve_schema` sends the full introspected schema (10 tables, about 3.4k prompt
tokens) until Phase 3 replaces it with hybrid RAG. `visualize`, grounded `explain` and `remember` arrive in
Phase 3.

### HTTP API (Phases 2–6)
The contract is exported with `python -m nexus.openapi` to `frontend/src/api/openapi.json` (snapshot
checked by a unit test) and turned into TypeScript types (`make api-types`).

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | public (rate-limited per IP and per email) | Returns an access token and sets the refresh cookie |
| POST | `/api/auth/refresh` | cookie | Rotates the refresh token; reusing an old one revokes the whole family |
| POST | `/api/auth/logout` | cookie | Revokes the session |
| GET | `/api/auth/me` | any role | Current user |
| POST | `/api/runs` | any role (rate-limited, one concurrent run per user) | Starts a run (`202` + `run_id`) |
| GET | `/api/runs` · `/api/runs/{id}` | owner or admin | History and the full result (steps, SQL, rows, attempts, assumptions, tokens) |
| GET | `/api/runs/{id}/events` | owner or admin | SSE stream with `Last-Event-ID` replay |
| DELETE | `/api/runs/{id}` | owner or admin | Cancel |
| GET | `/api/audit` | admin | Audit log of logins and every SQL attempt |
| POST | `/api/runs/{id}/feedback` | analyst, admin | Up/down rating; `verify: true` turns the steps into indexed few-shot examples |
| GET | `/api/memory/frequent` | any role | The user's most frequent questions |
| GET · PUT | `/api/memory/preferences` | any role | Locale, default chart, SQL visibility |
| GET | `/api/health/live` · `/api/health/ready` | public | Liveness and dependency readiness |
| GET · POST | `/api/dashboards` | any role (list) · analyst, admin (create) | Own and shared dashboards |
| GET · PATCH · DELETE | `/api/dashboards/{id}` | readable if owned/shared; changes by owner or admin | A dashboard with its pinned items rendered from the stored run results |
| POST · DELETE · PUT | `/api/dashboards/{id}/items[/{item}]` · `/items/order` | owner or admin | Pin a run step, unpin, reorder |
| GET | `/api/connections` · `/api/connections/{key}` | any role (network details: admin) | Data sources; one source with its tables (row estimates) and retrieval-index state |
| POST | `/api/connections/test` | admin | Probe a source: version, visible tables, whether the credentials can write |
| POST · DELETE | `/api/connections` · `/api/connections/{key}` | admin | Register (encrypted secret, `409` if writable and not acknowledged, `503` without keys) or delete; the built-in demo cannot be deleted |
| POST | `/api/connections/{key}/index` | admin | Rebuild the source's retrieval index in the background |
| GET | `/api/connections/sqlite-files` | admin | SQLite files available under the data directory |
| GET | `/api/runs/{id}/steps/{n}/annotation?locale=` | owner or admin | Clause-by-clause explanation with spans (ADR-0021) |
| POST | `/api/runs/{id}/steps/{n}/optimize` | owner or admin | Plan analysis, findings and index suggestions with cost before/after (ADR-0021) |
| GET | `/api/benchmark` | any role | Newest full golden-set run of each model configuration, the selected default and the serving model |
| GET | `/api/benchmark/runs/{id}` | any role | One run with every question's outcome, latency, repairs and SQL |

## 6. Request sequence (reference question)

> «¿Cuáles fueron los cinco productos más vendidos durante el último trimestre y qué sucursal generó mayores ingresos?»

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant API
    participant G as Agent graph
    participant L as Ollama
    participant V as Validator (SQLGlot)
    participant D as Demo DB (read-only)
    UI->>API: POST /api/runs {question}
    API-->>UI: 201 run_id
    UI->>API: GET /api/runs/{id}/events (SSE)
    API->>G: invoke(state)
    G->>L: understand → intent=data
    G->>L: embed(question) + FTS → sub-schema: productos, detalle_ventas, ventas, sucursales, devoluciones
    G->>L: plan → 2 steps (top-5 products by units, top branch by revenue)
    Note over G: resolve_time: "último trimestre" = 2026-07-01 ≤ fecha < 2026-10-01 (as_of 2026-11-01)
    loop each step
        G->>L: generate_sql (structured)
        G->>V: parse AST, enforce rules, add LIMIT
        V-->>G: ok
        G->>D: BEGIN READ ONLY, SET LOCAL statement_timeout, SELECT …
        D-->>G: rows
        G->>G: verify_results
    end
    G->>L: visualize + explain (grounding check)
    G-->>API: events (streamed as they happen)
    API-->>UI: node.* … run.completed
```

## 7. SQL safety — defense in depth

```mermaid
flowchart LR
    q[LLM output] --> s1[1 · Pydantic schema<br/>structured output only]
    s1 --> s2[2 · SQLGlot AST validation<br/>single SELECT/WITH SELECT · no DML/DDL in CTEs<br/>no SELECT INTO/COPY/CALL · function allow+deny lists<br/>schema/table allowlist · forced LIMIT]
    s2 --> s3[3 · Read-only DB role<br/>SELECT on allowed schema only<br/>no EXECUTE on dangerous functions]
    s3 --> s4[4 · Read-only transaction<br/>statement_timeout · lock_timeout<br/>row cap on fetch]
    s4 --> s5[5 · Separate pool<br/>never shares connections with app DB]
    s5 --> r[rows] --> s6[6 · PII masking + audit log]
```

- Layers 2 and 3 are each tested to stand alone: the attack suite runs once **with validation disabled
  against the read-only role** and once **with validation enabled against a privileged role**; both must block
  every destructive case (ADR-0005).
- Prompt-injection posture: user questions and database values are placed in clearly delimited data blocks,
  never concatenated into instructions; sample values are truncated and control characters stripped; the LLM has
  no tools — its only power is to propose SQL, which then goes through layers 2–5.

## 8. Retrieval (schema RAG)

```mermaid
flowchart LR
    subgraph index[Indexing — on connection add / refresh]
        intro[Introspect catalog<br/>tables · columns · types · FKs · COMMENTs] --> docs[Build documents<br/>table doc · column doc · sample values<br/>glossary terms · verified examples]
        docs --> emb[Ollama embeddings] --> pg[(schema_documents<br/>vector · tsvector)]
    end
    subgraph query[Query time]
        qq[standalone question] --> vec[pgvector HNSW<br/>cosine top-k]
        qq --> kw[Full-text spanish + unaccent<br/>+ pg_trgm on identifiers]
        vec --> rrf[Reciprocal Rank Fusion]
        kw --> rrf
        rrf --> exp[Expand: FK neighbours<br/>Steiner-tree join path over FK graph]
        exp --> ctx[Sub-schema + join path<br/>+ glossary + few-shot]
    end
    pg --> vec
    pg --> kw
```

Retrieval quality is measured independently (recall@k of gold tables from the benchmark's SQL), which is also
how the embedding model is chosen (ADR-0007).

## 9. Data model (app DB, abridged)

```mermaid
erDiagram
    users ||--o{ conversations : owns
    users ||--o{ refresh_tokens : has
    users ||--o{ user_preferences : has
    users ||--o{ dashboards : owns
    connections ||--o{ schema_documents : indexes
    connections ||--o{ glossary_terms : scopes
    connections ||--o{ verified_examples : scopes
    conversations ||--o{ runs : contains
    runs ||--o{ run_events : streams
    runs ||--o{ sql_attempts : tries
    runs ||--o| feedback : receives
    dashboards ||--o{ dashboard_items : pins
    runs ||--o{ dashboard_items : pinned_as
    users ||--o{ audit_log : acts
    benchmark_runs ||--o{ benchmark_results : contains

    connections {
        uuid id PK
        text kind
        text name
        bytea secret_enc
        date as_of
        jsonb allowlist
        jsonb pii_columns
    }
    schema_documents {
        uuid id PK
        uuid connection_id FK
        text doc_type
        text ref
        text content
        vector embedding
        tsvector tsv
    }
    runs {
        uuid id PK
        uuid conversation_id FK
        text question
        text status
        jsonb plan
        jsonb result_meta
        int total_ms
        int tokens
    }
    sql_attempts {
        uuid id PK
        uuid run_id FK
        int step
        int attempt
        text sql
        text error_code
        text error_message
    }
    audit_log {
        bigint id PK
        uuid user_id FK
        text question
        text sql
        text outcome
        int row_count
        int duration_ms
    }
```

## 10. Retail demo DB

Spanish identifiers (by spec): `regiones`, `sucursales`, `categorias`, `productos`, `clientes`, `empleados`,
`ventas`, `detalle_ventas` (~500k rows), `inventario`, `devoluciones`. Every table and column has `COMMENT ON`.
Ecuadorian context, amounts in **USD** (IVA 15 %). Data range **2024-11-01 → 2026-10-31**, generated by a seeded
script with weekly and annual seasonality (Navidad, Black Friday, Día de la Madre, décimo tercer/cuarto sueldo,
regional back-to-school calendars Sierra vs. Costa), a growth trend, and planted anomalies (stock-out, returns
spike, temporary closure, new branch, outlier order) — see ADR-0017. The demo connection has `as_of = 2026-11-01`,
so relative dates resolve deterministically regardless of the wall clock (ADR-0008).

## 11. Frontend

React 19 + TypeScript strict + Vite, Tailwind v4 with design tokens as CSS variables, shadcn/ui-style primitives
on Radix, Motion for transitions, TanStack Query (server state), TanStack Table v9 + Virtual (results grid),
ECharts 6 themed from the same tokens (lazy-loaded), Shiki (JS regex engine, CSS-variable theme) for SQL,
cmdk for the command palette, i18next (es default, en). Routes: `/login`, `/` (workspace, `?run=<id>` reopens
a run), `/dashboards`, `/dashboards/:id`, `/history`, `/connections`, `/benchmark`, `/audit` (admin),
`/settings`. The design system is in `docs/DESIGN.md`; the structural decisions are in ADR-0020.

```mermaid
flowchart LR
    subgraph Providers
      Q[QueryClient] --> P[Preferences<br/>theme · locale] --> A[Auth<br/>SessionManager] --> W[Workspace<br/>turns · SSE streams]
    end
    W --> R[Router]
    R --> WS[Workspace page<br/>QueryBar · Turns · AgentTimeline]
    R --> D[Dashboards] & H[History] & C[Connections] & B[Benchmark] & AU[Audit] & S[Settings]
    WS -->|fetch + ReadableStream| SSE[(GET /api/runs/:id/events)]
    WS -->|typed client| API[(REST /api/*)]
```

- **Session:** the access token lives in memory. The refresh token stays in an HttpOnly cookie; refreshes
  are coalesced and sent with `keepalive`.
- **Timeline:** a pure reducer turns zod-validated events into timeline items.
- **Results:** KPI cards plus Tabla/Gráfico/SQL/Explicación/Optimización tabs. Dashboards reference
  `(run, step)`.

## 12. Observability

- `structlog` JSON logs; `request_id` (from `X-Request-ID` or generated) bound in a contextvar and echoed in the response.
- Each graph node emits a span (`run_id`, `node`, `step`, `attempt`, duration, tokens, outcome) to the log
  stream **and** to `run_events`, which the UI and the audit page read. Optional OTLP exporter is out of scope for v1.
