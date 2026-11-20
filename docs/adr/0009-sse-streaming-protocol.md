# ADR-0009 — SSE streaming protocol for agent events

- Status: Accepted
- Date: 2026-11-20

## Context
The UI shows the agent "thinking" live. Traffic is one-directional (server → client) after the question is sent.

## Decision
- Two endpoints: `POST /api/runs` starts a run in a background task and returns `run_id`;
  `GET /api/runs/{id}/events` streams `text/event-stream` (via `sse-starlette`).
- Each event has a monotonically increasing `id`, a `event` type (`node.started`, `node.completed`,
  `node.failed`, `node.token`, `run.completed`) and a JSON payload validated by Pydantic models that are also
  exported as TypeScript types (generated from OpenAPI) so both sides share the contract.
- Events are persisted to `run_events` before being pushed to an in-process `asyncio.Queue` per run. Reconnects
  with `Last-Event-ID` replay from the table, then tail the queue. Heartbeat comment every 15 s.
- The client uses `fetch` + `ReadableStream` + a small spec-compliant SSE parser (unit-tested) so it can send
  `Authorization: Bearer`. Cancellation: `DELETE /api/runs/{id}` aborts the task.
- Payloads are summarized (SQL in full, rows truncated to a preview) to keep the stream light; full results are
  fetched via `GET /api/runs/{id}`.

## Alternatives considered
- WebSockets: bidirectional not needed; worse with proxies and auth middleware.
- `EventSource` with token in query string: leaks tokens into logs.
- Polling: no live feel.

## Consequences
- Single-replica assumption for the in-process queue; with multiple replicas, swap the queue for Postgres
  `LISTEN/NOTIFY` (already the event store), documented in PROGRESS.md as a known limitation.
