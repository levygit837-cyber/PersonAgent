# ADR 0010: Tool Registry + Orchestrator with Safe Parallelism and Permission System

Date: 2025-06-10
Status: Accepted

## Context

The agent can invoke 20+ tools (filesystem, shell, web, browser, LSP, MCP). We need safe execution: concurrency limits, permission gating, result size caps, and clean error handling.

## Decision

**ToolRegistry**
- Central register (`application/tools/registry.py`) holding all `ToolDefinition` instances.
- Tools are categorized by `ToolGroup` (`WORKSPACE`, `SHELL`, `WEB`, `AGENT`, `PLANNING`, `TASK`, `DISCOVERY`, `OUTPUT`, `LSP`, `CONFIG`, `WORKTREE`, `MCP`, `USER_INTERACTION`).
- Each tool declares metadata: `is_read_only`, `is_destructive`, `is_concurrency_safe`, `requires_user_interaction`, `max_result_size_chars`, `timeout_ms`.

**ToolOrchestrator**
- Partitions a batch of tool calls into safe parallel groups and serial sequences.
- Parallel batches run up to `max_concurrency` (default 4) and preserve call ordering via a result buffer.
- Serial execution for concurrency-unsafe or user-interaction tools.
- Emits `ToolExecutionEvent`s (started, progress, completed, error, permission_required) for SSE streaming.

**Permission System**
- `ToolPermissionBehavior` enum: `ALLOW`, `DENY`, `ASK`.
- `check_permissions()` on each tool evaluates runtime context (workspace grants, allowed roots, command allowlists).
- `ASK` triggers the action-approval flow (see ADR 0009).

**RuntimeConfig**
- Immutable dataclass (`application/tools/runtime_config.py`) holding limits: `max_tool_iterations`, `read_max_bytes`, `shell_timeout_ms`, `web_timeout_ms`, `result_max_chars`.

## Consequences

- **Easier**: new tools are registered in one place; parallel execution speeds up independent reads; permission errors are surfaced as structured SSE events.
- **Harder**: every tool must correctly declare `is_concurrency_safe` and `check_permissions`; misclassification leads to race conditions or security holes.
- **Risk**: destructive tools (`write_file`, `shell`) gated only by permission checks; a bug in the check bypasses the ASK gate.
- **Out of scope**: remote tool execution over RPC; tool sandboxing with containers.

## Alternatives Considered

- **Sequential-only execution**: rejected because it would make multi-file reads painfully slow.
- **Celery/queue-based tool execution**: rejected for latency and operational complexity.

## Validation

- `@backend/tests/unit/` has tests for batch partitioning, permission results, and timeout handling.
- `@backend/tests/test_browser_cooperation.py` validates browser tool permission gating.
