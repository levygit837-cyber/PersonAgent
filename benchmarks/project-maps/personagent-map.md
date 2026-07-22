# Project Map: PersonAgent

## Overview

**PersonAgent** is a local-first personal AI agent system that unifies intelligent chat, browser automation, Git workspace control, and long-term contextual memory into a single desktop application. It is designed for privacy with fallback to cloud LLM providers.

**Tech Stack:**
- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, structlog, typer, rich
- **Desktop:** Electron 41, React 19, TypeScript 5, Vite, Tailwind CSS, Zustand, TanStack Query
- **LLM/AI:** Multi-provider support — llama.cpp (TurboQuant KV-cache), NVIDIA NIM, Vertex AI, Kimi Coding, DeepSeek, OpenAI-compatible adapters
- **Data:** PostgreSQL 15, pgvector, local embeddings (GGUF), semantic operational memory
- **Browser:** Playwright, LightPanda/CDP, human-in-the-loop action approval
- **DevOps:** Docker Compose, GitHub Actions CI/CD, gitleaks, pre-commit, ruff, mypy, pytest, vitest

**Architecture Pattern:** Clean Architecture with strict dependency inversion. Domain layer contains pure models; Application layer orchestrates use cases; Infrastructure layer adapts external systems (DB, LLM, Browser); Interfaces layer exposes HTTP API and CLI.

---

## Directory Structure

```
/home/levybonito/Documentos/PersonAgent/
├── @backend/                          # FastAPI backend (Python)
│   ├── src/personagent/
│   │   ├── domain/                    # Pure models, exceptions, domain services
│   │   │   ├── prompts/               # Prompt system: builder, sections, surfaces, agent states
│   │   │   ├── memory/                # Memory models and domain services
│   │   │   ├── conversation/          # Conversation models and repositories (ports)
│   │   │   ├── context/               # Context builder domain models and services
│   │   │   ├── llm_backend/           # LLM backend ports (repository interfaces)
│   │   │   ├── tools/                 # Tool contracts and build_tool
│   │   │   ├── browser_workspace/     # Browser workspace repository ports
│   │   │   ├── security/              # Security value objects
│   │   │   └── exceptions/            # Domain-specific exception hierarchy
│   │   ├── application/               # Use cases, application services, DTOs
│   │   │   ├── use_cases/             # Chat completion, context build, memory CRUD
│   │   │   │   └── chat/              # Chat sub-orchestration: streaming, tooling, memory, lifecycle
│   │   │   ├── services/              # Operational memory, session titles, browser cooperation
│   │   │   ├── team_chat/             # Multi-agent team mode with blackboard and consensus
│   │   │   ├── tools/                 # Tool orchestrator, registry, runtime config
│   │   │   ├── qa/                    # QA tracing and indexing system
│   │   │   └── jobs/                  # Background memory consolidation workers
│   │   ├── infrastructure/            # External adapters and implementations
│   │   │   ├── llm/                   # LLM provider adapters (llama_cpp, nvidia, vertex, kimi, deepseek, codex)
│   │   │   ├── browser/               # CDP/LightPanda browser automation, snapshots, actions
│   │   │   ├── persistence/           # PostgreSQL repositories, Alembic migrations, operational memory recall
│   │   │   ├── tools/                 # Concrete tool implementations (browser, filesystem, git, shell, dev)
│   │   │   ├── settings/              # Pydantic-settings configuration
│   │   │   └── telemetry/             # OpenTelemetry spans and tracing
│   │   └── adapters/                  # Interface layer: HTTP API, CLI, TUI
│   │       ├── api/                   # FastAPI routes, middleware, SSE/WebSocket handlers
│   │       ├── cli.py                 # Typer CLI entrypoint
│   │       ├── tui/                   # Textual TUI widgets
│   │       └── composition/           # DI container wiring all layers together
│   ├── tests/                         # pytest suites (integration + unit)
│   ├── scripts/                       # Benchmarks, evaluation scripts
│   └── pyproject.toml
├── @desktop-electron/                 # Electron desktop app
│   ├── src/
│   │   ├── api/                       # HTTP/SSE client, workspace API, session API
│   │   ├── stores/                    # Zustand stores (chat, git, terminal, layout)
│   │   ├── types/                     # TypeScript domain types
│   │   ├── lib/                       # Utilities (todos, reasoning, highlighting)
│   │   └── ... (React components)
│   └── electron/                      # Main process, preload scripts, IPC
├── docs/                              # ADRs (25+), AI guides, architecture docs
├── benchmarks/                        # Benchmark specs, prompts, project maps
├── frontend/                          # Legacy HTML frontend
└── specs/                             # Implementation specs and plans
```

---

## Key Architectural Components

### 1. Chat Completion Pipeline (`application/use_cases/chat_completion.py`)
The central orchestrator for a single turn. It coordinates:
- **Context building** (`BuildContextUseCase`)
- **Prompt surface preparation** (`PromptSurfacePreparer`)
- **Memory recall** (`MemoryRecallCoordinator` — classic + operational)
- **Prompt package assembly** (`PromptPackageBuilder` → `PromptBuilder`)
- **Tool loop** with iteration limits and evidence gates
- **Streaming** via `StreamingTurnExecutor` (async iterator of `StreamChunk`)
- **After-turn cleanup** (session titles, operational memory capture, background memory extraction)

### 2. Prompt System (`domain/prompts/`)
A highly dynamic, section-based prompt builder:
- **`PromptBuilder`** (`services/prompt_builder/prompt_builder.py`): Assembles the full system prompt from 4 parts: base sections, tool sections, execution sections, agent sections. Supports caching per scope.
- **`AgentStateResolver`** (`services/agent_state_resolver.py`): Heuristic resolver that maps user message + conversation metadata → active agent states (e.g., `context_discovery`, `tool_execution`, `debug_recovery`). Uses term matching and profile analysis.
- **Prompt Sections** (`sections/`): Each section is a `SystemPromptSection` with a `compute` callable. Sections can be cache-breaking (recomputed every turn) or cached.
- **Prompt Surfaces** (`surfaces.py`): Metadata hints about which prompt surfaces (memory, tool, next_step, etc.) are active.
- **Context Attachments** (`context_attachments/`): Resolvers for browser, file, and other context attachments injected into prompts.

### 3. Tool Runtime (`application/tools/`)
- **`ToolRegistry`** (`registry.py`): Lookup by name/alias, OpenAI schema generation with caching, allowlist filtering, deferred loading.
- **`ToolOrchestrator`** (`orchestrator/_core.py`): Batches tool calls into concurrency-safe vs serial groups, executes parallel batches with bounded concurrency, emits progress events.
- **`ToolRuntime`** (`application/use_cases/chat/tooling/tool_runtime.py`): Per-turn helper that resolves schemas, creates orchestrators, and computes effective iteration limits based on investigation depth policies.
- **Concrete Tools** (`infrastructure/tools/`): Browser (navigation, interaction, screenshot), filesystem (read, write, search), Git (status, diff, commit, PR), shell (with path safety), dev (LSP, worktree).

### 4. Memory System (`domain/memory/` + `application/services/operational_memory/`)
Two-tier memory:
- **Classic Memory**: File-backed, project-scoped memory with semantic recall via pgvector embeddings. `MemoryRepository` manages memory files; `MemoryRecallCoordinator` deduplicates across turns.
- **Operational Memory**: Short-term execution history (tool calls, errors, completions). `OperationalMemoryService` formats recent events into prompt blocks. Falls back to `latest_only` if primary recall is empty.
- **Background Jobs** (`application/jobs/`): Scheduled workers extract and consolidate memories asynchronously.

### 5. Team Chat / Multi-Agent (`application/team_chat/`)
Phase-based multi-agent orchestration:
- **`TeamChatOrchestrator`** → **`TeamChatPhaseLoop`**: Drives execution contract → independent/debate rounds → consensus vote → final synthesis.
- **Blackboard** (`blackboard/`): Shared state across agents with claim graphs, coherency scoring, and workspace memory compaction.
- **Consensus Phase** (`phases/consensus.py`): Agents vote on proposals; fast-vote optimization for simple cases.
- **`AgentTurnRunner`**: Runs individual agent turns in parallel during rounds.

### 6. LLM Backend Adapters (`infrastructure/llm/`)
Pluggable provider adapters implementing `LLMBackendRepository`:
- **llama.cpp** (`llama_cpp_adapter.py`): OpenAI-compatible local server with reasoning tag parsing, tool call accumulation.
- **NVIDIA NIM** (`nvidia_nim_adapter/`): Payload normalization, streaming.
- **Vertex AI** (`vertex_ai/`): Content builder, streaming adapter.
- **Kimi** (`kimi/`): Coding adapter with history management.
- **DeepSeek**, **Codex** (`deepseek_adapter.py`, `codex/`): Specialized adapters.
- **Shared** (`shared/`): OpenAI-compatible parser, thinking tag splitting, tool call delta accumulation, embedding adapter.

### 7. Browser Automation (`infrastructure/browser/`)
- **LightPanda/CDP runtime** (`lightpanda/`): Page lifecycle, navigation, markdown extraction.
- **Snapshot pipeline** (`snapshot/`): DOM element detection, style extraction, tab management.
- **Actions** (`actions/`): Click, type, scroll, screenshot, script injection, console capture.
- **Browser Cooperation** (`application/services/browser_cooperation/`): Human-in-the-loop action approval with redaction and event processing.

### 8. Evidence Gate (`application/use_cases/chat/evidence_gate.py`)
A preventive loop-control mechanism for codebase-analysis turns. It checks objective coverage metrics (files read, searches made) and decides whether the model should continue gathering evidence or is ready to synthesize a final answer. Policies vary by `InvestigationDepth` (`light` → `exhaustive`).

---

## Dependency Map

### Internal Layer Dependencies
```
Interfaces (API/CLI/TUI)
    ↓ depends on
Application (Use Cases + Services)
    ↓ depends on
Domain (Models + Ports)
    ↓ (no framework deps)
Infrastructure (Adapters implement Domain Ports)
    ↓ depends on external libs
External: PostgreSQL, LLM APIs, Browser CDP, Filesystem
```

### Key Cross-Module Dependency Chains
- `ChatCompletionUseCase` → `StreamingTurnExecutor` → `AssistantPassRunner` → `LLMBackendRepository`
- `ChatCompletionUseCase` → `PromptPackageBuilder` → `PromptBuilder` + `AgentStateResolver`
- `ChatCompletionUseCase` → `ToolRuntime` → `ToolRegistry` + `ToolOrchestrator`
- `ChatCompletionUseCase` → `MemoryRecallCoordinator` → `RecallMemoryUseCase` + `OperationalMemoryService`
- `TeamChatOrchestrator` → `TeamChatPhaseLoop` → `AgentTurnRunner` → (reuses single-agent chat path)
- `DIContainer` (composition root) mixes infrastructure and application mixins to wire all collaborators.

### Key External Dependencies
- FastAPI, uvicorn, httpx, websockets
- SQLAlchemy (async), asyncpg, alembic, pgvector
- playwright (browser automation)
- tenacity (retry logic)
- structlog (structured logging)
- opentelemetry (tracing)

---

## Informational Goals (Benchmark Candidates)

### Goal 1: Evidence Gate Loop Control
- **Question**: "When the model signals `ready_for_final=True` during a streaming chat turn, under what exact conditions does the `StreamingTurnExecutor` override the model's readiness and force another evidence-gathering iteration instead of breaking the loop?"
- **Why it's hard**: The decision spans three files (`executor.py`, `evidence_gate.py`, `tool_runtime.py`) and involves both model-driven readiness and gate-driven coverage checks. The override logic depends on `turn_state.iteration`, `effective_max_iterations`, `tool_context` presence, and whether the gate's `should_continue` returns true.
- **Expected findings**: The executor has two distinct paths — model-ready path (checks `assistant_state.ready_for_final`) and gate-initiated path. In both, if `decision.should_continue` is true AND `tool_context` is not None AND iteration is below limit minus one, the loop continues with an evidence gate reminder. The `EvidenceGateService` checks objective `TurnCoverage` (files_read count, search_patterns, tool_names).
- **Complexity**: complex
- **Key files involved**: `application/use_cases/chat/streaming/executor.py`, `application/use_cases/chat/evidence_gate.py`, `application/use_cases/chat/tooling/tool_runtime.py`, `application/use_cases/chat/messaging/state.py`

### Goal 2: Prompt Builder Section Cache Invalidation
- **Question**: "How does the `PromptBuilder` decide whether a specific `SystemPromptSection` should be cached or recomputed on every turn, and what inputs form the `cache_scope` hash that keys the cache?"
- **Why it's hard**: The caching logic is distributed across `prompt_builder.py` (cache lookup, scope generation), `models.py` (`cache_break` field on `SystemPromptSection`), and the section resolution loop. The cache scope hash is built from workspace, prompt mode, agent states, permission mode, provider, model, and tool names — but this is assembled in a private method.
- **Expected findings**: Sections with `cache_break=True` are NEVER cached and are deferred to the dynamic boundary of the assembled prompt. Sections with `cache_break=False` are cached under a SHA256 hash of workspace|prompt_mode|agent_states|permission_mode|provider|model|sorted_tools. The `_resolve_sections` method skips cache lookup for cache-breaking sections.
- **Complexity**: medium
- **Key files involved**: `domain/prompts/services/prompt_builder/prompt_builder.py`, `domain/prompts/models.py`, `domain/prompts/services/prompt_builder/_sections.py`

### Goal 3: Agent State Resolution Heuristics
- **Question**: "If a user sends the message 'plan a migration strategy to deploy the new auth service to production' in `auto` prompt mode, what exact sequence of `AgentState` values will the `AgentStateResolver` produce, and which heuristic terms trigger each state beyond the default `intake` and `finalization`?"
- **Why it's hard**: Requires tracing through the `AgentStateResolver.resolve()` method which has 15+ conditional branches, Portuguese/English term lists, and cross-dependencies between `prompt_profile.primary_mode`, message text, metadata flags, and conversation statistics. The resolver is heuristic and state ordering matters.
- **Expected findings**: States would include: `intake` (default), `planning` ("plan" + "strategy" terms), `tool_execution` (tools available), `user_checkpoint` (long-running terms like "complex" or "end-to-end"), `runtime_validation` ("production" triggers via research/writing mode or validation terms), and `finalization`. The exact order and deduplication must be traced.
- **Complexity**: complex
- **Key files involved**: `domain/prompts/services/agent_state_resolver.py`, `domain/prompts/models.py`

### Goal 4: Tool Execution Parallelism and Ordering
- **Question**: "When the `ToolOrchestrator` receives a list of 5 tool calls where calls 1, 2, and 4 are concurrency-safe but call 3 is not, and `max_concurrency=2`, how many `_ToolBatch` partitions are created and in what order are results yielded to the consumer?"
- **Why it's hard**: The partitioning logic in `_partition()` is subtle — it merges consecutive concurrency-safe calls up to `max_concurrency`, but a non-safe call breaks the batch. Result yielding for parallel batches uses an ordered buffer (`result_buffer`) to preserve original call order even though tasks complete asynchronously.
- **Expected findings**: Partitions would be: Batch 1 [call1, call2] (concurrency_safe=True), Batch 2 [call3] (concurrency_safe=False), Batch 3 [call4] (concurrency_safe=True, new batch because prior was non-safe). Call 5's batch depends on its safety. For parallel batches, results are buffered by original index and yielded in index order via `next_result_index`.
- **Complexity**: medium
- **Key files involved**: `application/tools/orchestrator/_core.py`, `application/tools/orchestrator/_execution.py`

### Goal 5: Memory Recall Fallback Chain
- **Question**: "During a chat turn, if the primary operational memory recall returns an empty package, what fallback mechanism ensures the agent still receives some execution context, and how does the `MemoryRecallCoordinator` prevent the same classic memories from being resurfaced on consecutive turns?"
- **Why it's hard**: The fallback spans `_run_operational_recall` (with `latest_only=True` retry) and `_run_classic_recall` (with `_surfaced_memory_paths` deduplication on conversation metadata). These are in the same file but the interaction with conversation state is implicit.
- **Expected findings**: Operational recall falls back to a `latest_only=True` query when the primary package is empty. Classic recall tracks surfaced paths in `conversation.metadata["_surfaced_memory_paths"]` and passes `already_surfaced` to the recall use case; new paths are appended back to metadata. The `MemoryTraceBuilder` combines both classic and operational traces.
- **Complexity**: medium
- **Key files involved**: `application/use_cases/chat/memory/memory_recall.py`, `domain/memory/services/memory_trace.py`, `application/services/operational_memory/service.py`

### Goal 6: Investigation Depth Policy Enforcement
- **Question**: "How does the `ToolRuntime` determine the effective maximum tool iteration count for a chat request with `investigation_depth='deep'`, and what evidence checklist items must be satisfied before the `EvidenceGateService` allows a final answer for that depth?"
- **Why it's hard**: The iteration limit is resolved through a precedence chain (request override → runtime config → investigation depth policy → safety ceiling), defined across `tool_runtime.py` and `runtime_config.py`. The evidence checklist is defined in `INVESTIGATION_DEPTH_POLICIES` in `tool_runtime.py` but evaluated by `EvidenceGateService` which only checks a subset of objective facts.
- **Expected findings**: For `deep`, `max_tool_iterations=100` and `max_evidence_gate_continuations=3`. The effective limit uses `resolve_effective_tool_iterations()` which caps at `SAFETY_TOOL_ITERATION_CEILING`. The minimum evidence checklist for `deep` includes: `has_tool_calls`, `has_search_evidence`, `has_file_read_evidence`, `has_core_implementation_read`, `has_caller_or_symbol_search`, `has_test_evidence`, `has_manifest_evidence`, `has_adjacent_module_evidence`. However, the actual gate only enforces files_read count and search patterns — the checklist is aspirational.
- **Complexity**: complex
- **Key files involved**: `application/use_cases/chat/tooling/tool_runtime.py`, `application/tools/runtime_config.py`, `application/use_cases/chat/evidence_gate.py`, `application/use_cases/chat/messaging/state.py`

### Goal 7: Team Chat Phase Loop Consensus Flow
- **Question**: "In Team Mode, after the `AgentTurnRunner` completes parallel agent turns for round 2 (debate phase), what sequence of events triggers the consensus vote, how is the vote result evaluated, and what happens if consensus is NOT reached?"
- **Why it's hard**: The phase loop (`loop.py`) delegates to sub-modules (`_debate.py`, `_consensus.py`), uses the blackboard's `vote_triggers()` method, has a fast-vote optimization path, and manages round advancement or failure. The flow crosses `TeamChatPhaseLoop`, `ConsensusPhase`, `Blackboard`, and `AgentTurnRunner`.
- **Expected findings**: After agent turns, `blackboard.vote_triggers(round_index, team)` is checked. If triggers exist, an adaptive vote event is emitted. If fast vote is enabled and `blackboard.fast_vote_ready()`, synthetic votes are generated; otherwise `ConsensusPhase.run_vote()` is called per agent. Consensus requires `approvals >= ceil(len(agents) * threshold)` AND no critical blocker. If not reached, `round_index += 1` and the loop continues up to `SAFETY_TEAM_ROUND_CEILING`. If the round cap is hit, `_team_consensus_failed_event` is yielded.
- **Complexity**: very complex
- **Key files involved**: `application/team_chat/orchestration/orchestrator.py`, `application/team_chat/phases/loop/loop.py`, `application/team_chat/phases/consensus.py`, `application/team_chat/blackboard/core.py`, `application/team_chat/orchestration/agent_turn_runner.py`, `application/team_chat/phases/loop/_events.py`

---

## Complexity Assessment

**Overall Rating: Very Complex**

**Reasoning:**

1. **Layered Clean Architecture with 250+ Python modules**: The backend alone has deep layering (Domain → Application → Infrastructure → Interfaces) with strict dependency rules, making it non-trivial to trace execution paths.

2. **Dual Streaming + Synchronous Chat Paths**: The chat completion system maintains two parallel implementations (`execute` and `execute_stream`) that share collaborators but have different control flow, state management (dataclasses like `StreamingTurnState`, `AssistantStreamState`), and error handling.

3. **Dynamic Prompt Assembly with Caching and Heuristics**: The prompt system is one of the most intricate parts — it combines section-based caching, agent state heuristics (Portuguese + English term matching), prompt surface hints, context attachments, and provider-specific boundaries into a single coherent prompt.

4. **Multi-Modal Tool Orchestration**: Tool execution supports parallel batches with bounded concurrency, serial fallback, progress callbacks, artifact storage, and result capping. The partitioning logic and ordered result buffering are subtle.

5. **Two-Tier Memory with Background Jobs**: Classic memory (semantic, file-backed) and operational memory (execution history) have independent recall paths, deduplication strategies, and background consolidation workers.

6. **Multi-Agent Team Mode with Consensus**: The team chat system introduces a blackboard pattern, claim graphs, debate rounds, voting phases, and coordinator synthesis — all emitting WebSocket events. This is essentially a second chat orchestrator layered on top of the first.

7. **Multi-Provider LLM Adapter Ecosystem**: 6+ LLM providers with custom payload normalization, streaming parsers, reasoning tag handling, and tool call delta accumulation. Each adapter has its own quirks.

8. **Browser Automation + Human-in-the-Loop**: CDP-based browser control with action approval, redaction, snapshot pipelines, and cooperation state machines adds significant surface area.

**Most Complex Areas (ranked):**
1. **Chat Completion Streaming Turn Executor** — The async iterator loop integrating tool calls, evidence gates, memory recall, prompt building, and retry logic.
2. **Team Chat Phase Loop** — Multi-agent orchestration with consensus, blackboard, and event emission.
3. **Prompt Builder + Agent State Resolver** — Dynamic heuristic prompt assembly with caching and state inference.
4. **Browser Automation Stack** — CDP runtime, snapshot pipeline, cooperation service, and action arbiter.
5. **Memory Recall Coordination** — Bridging classic and operational memory with deduplication and fallbacks.
