# ADR 0023: Intra-Turn Dynamic Prompt Builder via Deterministic Phase Classification

Date: 2025-05-24
Status: Proposed

## Context

ADR 0007 introduced the modular prompt system with `PromptContextAnalyzer` (LLM-based, pre-turn) and `AgentStateResolver` (heuristic, pre-turn). Both resolve state **once before the turn starts**. During the tool loop (`StreamingTurnExecutor.run`), the system prompt remains static across all iterations.

This creates a mismatch: an agent that starts a turn exploring code and transitions to writing code mid-loop continues receiving explorer-optimized prompts. The system has no mechanism to adapt prompt guidance as the agent's execution phase shifts within a single turn.

The core constraint is latency. Any intra-loop classification must complete in sub-millisecond time — LLM calls (2–12 s) and embedding lookups (5–50 ms) are too slow for a hot path that runs on every tool-loop iteration.

## Decision

Add a **deterministic phase classifier** that runs inside the tool loop and hot-swaps only the dynamic prompt layer when the execution phase changes.

### Phase Enum

A new `AgentPhase` enum represents the agent's observable execution behavior at each loop iteration:

```
intake → exploring → planning → writing → testing → using_browser → debugging → finalizing
```

These are distinct from the existing `AgentState` values. `AgentState` captures pre-turn intent heuristics (what the agent *should* do). `AgentPhase` captures intra-turn runtime observation (what the agent *is doing*).

### Classification — Signal-Based State Machine

The classifier uses signals already present in memory at each loop iteration:

| Signal | Source | I/O Cost |
|--------|--------|----------|
| Last tool names executed | `tool_calls` / `results_by_id` | 0 |
| Tool result statuses | `ToolResult.status` | 0 |
| Iteration count | `turn_state.iteration` | 0 |
| Finish reason | `assistant_state.finish_reason` | 0 |
| Has visible content | `assistant_state.content` | 0 |
| Has pending tool calls | `assistant_state.tool_calls` | 0 |

Classification rules (ordered by priority):

1. **iteration == 0** → `intake`
2. **any tool status == ERROR** → `debugging`
3. **tool set ∩ browser_tools ≠ ∅** → `using_browser`
4. **tool set ∩ write_tools ≠ ∅** → `writing`
5. **tool set ∩ test_tools ≠ ∅** → `testing` (with command-content heuristic for `ShellExec`)
6. **tool set ∩ planning_tools ≠ ∅** → `planning`
7. **tool set ∩ read_tools ≠ ∅** → `exploring`
8. **no tool calls + has content** → `finalizing`
9. **default** → `exploring`

Estimated latency: **~0.05 ms** per classification (set intersection on small sets, no I/O).

### Prompt Layering

The system prompt is split into two layers:

```
┌──────────────────────────────────┐
│ STATIC LAYER (cached per turn)   │  Built once by PromptBuilder.build()
│ - Identity, rules, style         │
│ - Tool definitions & schemas     │
│ - Execution policy               │
│ - Provider boundary              │
├──────────────────────────────────┤
│ DYNAMIC LAYER (per iteration)    │  Hot-swapped on phase transition
│ - Phase-specific instructions    │
│ - Runtime reminders              │
│ - Agent state refinements        │
└──────────────────────────────────┘
```

Phase-specific prompt blocks are pre-rendered string constants (~500–2000 chars each). On a phase transition, only the dynamic layer is replaced via string concatenation. Estimated swap cost: **~0.1 ms**.

### Hook Point

Inside `StreamingTurnExecutor.run`, between message preparation and the assistant pass:

```
while True:
    messages, context = prepare(...)
    ┌── classify_phase(turn_state signals)
    │   if phase changed → rebuild_dynamic(prompt_package, new_phase)
    └── assistant_pass_runner.run(messages, tools)
    ... tool execution ...
    turn_state.iteration += 1
```

### Files Changed

| File | Change |
|------|--------|
| `domain/prompts/models.py` | Add `AgentPhase` enum |
| `domain/prompts/services/phase_classifier.py` | New: deterministic classifier |
| `domain/prompts/sections/phases.py` | New: phase-specific prompt constants |
| `application/use_cases/chat/state.py` | Add `current_phase`, `last_tool_names`, `last_tool_statuses` to `StreamingTurnState` |
| `application/use_cases/chat/streaming_turn.py` | Classification hook in the loop |
| `application/use_cases/chat/prompt_package.py` | `rebuild_dynamic()` method |
| `domain/prompts/services/prompt_builder.py` | Partial rebuild support (dynamic layer only) |

## Consequences

- **Easier**: agent prompts adapt mid-turn as execution context shifts; phase transitions are logged for observability; phase-specific instructions can be tuned independently.
- **Harder**: two overlapping state concepts (`AgentState` pre-turn + `AgentPhase` intra-turn) that must stay coherent; tool-set classification rules need maintenance when new tools are added.
- **Risk**: misclassification from ambiguous tool usage (e.g., `ShellExec` used for both testing and writing); prompt swap mid-conversation may confuse models that track instruction consistency.
- **Out of scope**: LLM-based intra-turn reclassification; automatic prompt compression; per-phase tool filtering (tools remain constant within a turn).

## Alternatives Considered

- **LLM-based intra-turn classifier**: rejected because even the fastest providers add 1–2 s latency per iteration, which is unacceptable in a hot loop.
- **Embedding similarity classifier**: rejected because cosine similarity on tool names/content is imprecise (5–50 ms) and requires a trained embedding space.
- **Secondary agent for state classification**: rejected because any cross-process or cross-model call exceeds the sub-millisecond budget.
- **Extend AgentStateResolver to run intra-turn**: rejected because the resolver uses message-level keyword heuristics that don't capture tool-execution signals; extending it would conflate two distinct concerns.

## Validation

- `phase_classifier.py` must have unit tests covering all transition rules with mock tool-call data.
- Integration test: a multi-iteration tool loop with mixed tool types must produce the expected phase sequence.
- Regression: existing `test_browser_tools_helpers.py` and `test_prompt_builder.py` suites must remain green (phase classification is additive, no existing behavior changes).
- Observability: phase transitions are emitted as `StreamChunk` metadata events (`event: "phase_transition"`) for telemetry dashboards.
- Latency budget: classification + swap must stay under 1 ms per iteration, verified by a benchmark test.
