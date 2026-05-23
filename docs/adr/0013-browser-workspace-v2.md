# ADR 0013: Browser Workspace V2 with LightPanda/CDP Dual-Runtime and DB Persistence

Date: 2025-06-10
Status: Accepted

## Context

The agent needs to browse the web, read documentation, interact with web apps, and cooperate with the user on a shared browser view. A lightweight, programmatic browser runtime must coexist with optional Chrome DevTools Protocol (CDP) access.

## Decision

**Dual runtime**
- **LightPanda** (default): headless, fast, low-memory HTML mirror with element mapping.
- **CDP/Chrome** (optional): full fidelity when `browser_cdp_url` is configured; the same `LightPandaBrowserWorker` adapts to CDP via Playwright.

**LightPandaBrowserWorker**
- Manages per-conversation browser sessions, page caches, render snapshots, stylesheet caches, and console logs.
- Auto-starts LightPanda container if not running and `auto_start_lightpanda=True`.
- Warmup is best-effort; tools report actionable errors if unavailable.

**V2 Persistence**
- `BrowserWorkspaceService` persists tabs, annotations, and timeline events to PostgreSQL (`browser_workspaces`, `browser_tabs`, `browser_annotations`, `browser_timeline_events`).
- Large HTML snapshots remain transient; only lightweight metadata and annotations are durable.
- Legacy metadata in `Conversation.metadata["browser_workspace""]` is migrated automatically on first access.

**Annotations**
- Anchored to DOM node IDs with selectors, frame IDs, and shadow paths.
- Created via API, surfaced in the timeline, and deleted individually.

## Consequences

- **Easier**: persistent browser state survives restarts; annotations allow collaborative research; dual runtime covers both speed and fidelity needs.
- **Harder**: CDP methods are allowlisted (`Runtime.evaluate`, `DOM.querySelector`, etc.) to prevent arbitrary code execution; CSS fidelity varies between runtimes.
- **Risk**: browser sessions have a TTL; abandoned sessions leak memory if not closed.
- **Out of scope**: pixel-perfect visual regression testing; mobile viewport emulation.

## Alternatives Considered

- **Playwright-first only**: rejected because Playwright + Chromium is heavy and slow for simple read tasks.
- **Selenium**: rejected for verbosity and slower startup.

## Validation

- `@backend/tests/test_browser_cooperation.py` validates tool calls and annotation CRUD.
- `BrowserWorkspaceService` integration tests verify legacy metadata migration.
