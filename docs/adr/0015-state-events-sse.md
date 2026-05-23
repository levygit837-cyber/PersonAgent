# ADR 0015: Server-Sent Events (SSE) for Lightweight State Invalidation and Git Signatures

Date: 2025-06-10
Status: Accepted

## Context

The Electron desktop needs to stay in sync with backend state changes (conversation updates, tool approvals, memory jobs, git status) without polling. WebSockets are too heavy for one-way push; SSE is simpler and firewall-friendly.

## Decision

Use **Server-Sent Events** as the primary one-way push channel from backend to desktop.

**Event types**
- `state.invalidation`: cache keys that the frontend should drop.
- `git.signature`: workspace git status changes (branch, dirty files, ahead/behind).
- `plan_mode_changed`: plan mode transitions (draft -> awaiting_approval).
- `memory_job_update`: extraction or consolidation job progress.
- `browser_workspace_update`: browser view mutations.

**Implementation**
- `interfaces/api/state_events.py` exposes `GET /state/events`.
- `StateManager` (`application/state/`) holds an in-memory registry of active SSE queues per client.
- Clients reconnect automatically; the backend emits a `connected` event on each new stream.

**Scope**
- One-way only. The desktop still uses REST for mutations.
- Not used for team mode (that uses WebSocket for bidirectional control).

## Consequences

- **Easier**: automatic reconnection; lightweight over HTTP/1.1 and HTTP/2; no WebSocket handshake overhead.
- **Harder**: no native binary payload support; large payloads must be split or referenced.
- **Risk**: if the backend restarts, all SSE connections drop; clients must detect this and re-fetch state.
- **Out of scope**: bidirectional SSE (POST-to-SSE); cross-tab broadcast (each tab has its own connection).

## Alternatives Considered

- **WebSocket for everything**: rejected because most events are one-way push; WebSocket adds complexity for no benefit.
- **Long-polling**: rejected for latency and connection overhead.

## Validation

- Desktop reconnects within 3 seconds of a backend restart.
- `@backend/tests/integration/` validates SSE stream formatting and event delivery.
